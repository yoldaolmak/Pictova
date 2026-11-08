"""Studio -> real native image pipeline -> synthetic WordPress REST -> verified manifest.

Only external discovery and vision *evidence* are deterministic fixtures. Real
HTTP, auth, Studio approval, processing, quality gate, metadata, WebP upload,
Gutenberg insertion, read-after-write and rollback execute without shortcuts.
The synthetic WordPress server binds to 127.0.0.1 and never uses site secrets.
These tests do NOT establish real-world recognition or live WordPress behavior.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image
import pytest
import requests

from src.pictova.app import server as app_server
from src.pictova.app import studio
from src.pictova.app.state import JobRegistry
from src.pictova.engine import attach, metadata, processor
from src.pictova.engine.image_processing import YOImageProcessor
from src.services import wordpress
from src.services.post_media_guard import assess_post_media, load_post_media_manifest, media_items_from_content


POST_ID = 731
SLUG = "kapadokya-sentetik-test"
PUBLIC_URL = f"https://synthetic.pictova.invalid/{SLUG}.html"
TOKEN = "pictova-isolated-wordpress-proof-token-20261108"
HEADING_A = "Uçhisar Kalesi"
HEADING_B = "Avanos Çömlekçiliği"
ARTICLE = (
    "<!-- wp:paragraph -->\n"
    "<p>Sentetik Kapadokya yazısının orijinal giriş paragrafı.</p>\n"
    "<!-- /wp:paragraph -->\n"
    "<!-- wp:heading -->\n<h2>Uçhisar Kalesi</h2>\n<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n<p>Uçhisar hakkında korunan editör metni.</p>\n<!-- /wp:paragraph -->\n"
    "<!-- wp:heading -->\n<h2>Avanos Çömlekçiliği</h2>\n<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n<p>Avanos hakkında korunan editör metni.</p>\n<!-- /wp:paragraph -->\n"
)


@dataclass
class FakeWordPressState:
    post_content: str = ARTICLE
    modified_revision: int = 0
    next_media_id: int = 901
    media: dict[int, dict] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    denied_post_update: bool = False
    suppress_inserted_blocks: bool = False
    auth_failures: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)

    def post_json(self):
        return {
            "id": POST_ID,
            "slug": SLUG,
            "status": "publish",
            "modified": f"2026-11-08T09:00:{self.modified_revision:02d}",
            "modified_gmt": f"2026-11-08T06:00:{self.modified_revision:02d}",
            "title": {"rendered": "Kapadokya Sentetik Test", "raw": "Kapadokya Sentetik Test"},
            "excerpt": {"raw": "Özgün sentetik yazı.", "rendered": "Özgün sentetik yazı."},
            "content": {"raw": self.post_content, "rendered": self.post_content},
        }


class FakeWordPressHandler(BaseHTTPRequestHandler):
    server_version = "SyntheticWordPressREST/1"

    def log_message(self, *_args):
        return

    @property
    def state(self):
        return self.server.state

    def _send(self, status: int, payload: dict | list):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authenticated(self) -> bool:
        expected = "Basic " + base64.b64encode(b"pictova-test-user:pictova-test-password").decode("ascii")
        if self.headers.get("Authorization") != expected:
            with self.state.lock:
                self.state.auth_failures += 1
            self._send(401, {"code": "rest_not_logged_in", "message": "Synthetic authentication required"})
            return False
        return True

    def do_GET(self):
        if not self._authenticated():
            return
        route = urlsplit(self.path)
        with self.state.lock:
            self.state.calls.append(("GET", route.path))
            if route.path == "/wp-json/wp/v2/posts":
                slug = parse_qs(route.query).get("slug", [""])[0]
                return self._send(200, [{"id": POST_ID, "slug": SLUG}] if slug == SLUG else [])
            if route.path == f"/wp-json/wp/v2/posts/{POST_ID}":
                return self._send(200, self.state.post_json())
        return self._send(404, {"code": "rest_post_invalid_id"})

    def do_POST(self):
        if not self._authenticated():
            return
        route = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > 6 * 1024 * 1024:
            return self._send(413, {"code": "synthetic_payload_too_large"})
        raw = self.rfile.read(length)
        with self.state.lock:
            self.state.calls.append(("POST", route))
            if route == "/wp-json/wp/v2/media":
                # Exercise the real Pictova WebP output, not a mocked upload.
                if self.headers.get("Content-Type") != "image/webp":
                    return self._send(415, {"code": "rest_upload_invalid_file_type"})
                try:
                    with Image.open(BytesIO(raw)) as image:
                        image.verify()
                    with Image.open(BytesIO(raw)) as image:
                        if image.format != "WEBP" or image.size != (1200, 750):
                            return self._send(422, {"code": "wrong_image_format_or_size"})
                except (OSError, ValueError):
                    return self._send(422, {"code": "corrupt_webp_upload"})
                media_id = self.state.next_media_id
                self.state.next_media_id += 1
                source_url = f"http://127.0.0.1:{self.server.server_port}/uploads/{media_id}.webp"
                self.state.media[media_id] = {
                    "id": media_id, "bytes": raw, "source_url": source_url,
                    "post": 0, "metadata": {},
                }
                return self._send(201, {"id": media_id, "source_url": source_url})

            if route.startswith("/wp-json/wp/v2/media/"):
                media_id = int(route.rsplit("/", 1)[-1])
                item = self.state.media.get(media_id)
                if item is None:
                    return self._send(404, {"code": "rest_invalid_media_id"})
                value = json.loads(raw)
                if "post" in value:
                    if value["post"] != POST_ID:
                        return self._send(422, {"code": "invalid_parent_post"})
                    item["post"] = POST_ID
                else:
                    item["metadata"].update(value)
                return self._send(200, {"id": media_id, "post": item["post"], "source_url": item["source_url"]})

            if route == f"/wp-json/wp/v2/posts/{POST_ID}":
                if self.state.denied_post_update:
                    return self._send(409, {"code": "synthetic_edit_conflict"})
                updated = json.loads(raw)
                if not isinstance(updated.get("content"), str):
                    return self._send(400, {"code": "invalid_post_content"})
                if not self.state.suppress_inserted_blocks:
                    self.state.post_content = updated["content"]
                # Simulates WordPress confirming a write without retaining
                # the submitted Gutenberg blocks when suppress=True.
                self.state.modified_revision += 1
                return self._send(200, self.state.post_json())
        return self._send(404, {"code": "rest_route_not_found"})

    def do_DELETE(self):
        if not self._authenticated():
            return
        route = urlsplit(self.path)
        if not route.path.startswith("/wp-json/wp/v2/media/"):
            return self._send(404, {"code": "rest_route_not_found"})
        media_id = int(route.path.rsplit("/", 1)[-1])
        if parse_qs(route.query).get("force") != ["true"]:
            return self._send(400, {"code": "force_required"})
        with self.state.lock:
            self.state.calls.append(("DELETE", route.path))
            if self.state.media.pop(media_id, None) is None:
                return self._send(404, {"code": "rest_invalid_media_id"})
            return self._send(200, {"deleted": True, "previous": {"id": media_id}})


def _start_server(handler, *, state=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if state is not None:
        server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _source_photo(path: Path, seed: int):
    """Generated photo-like pixels with enough detail for the *real* quality gate."""
    rng = np.random.default_rng(seed)
    tiles = rng.integers(45, 205, size=(50, 80, 3), dtype=np.uint8)
    pixels = np.repeat(np.repeat(tiles, 16, axis=0), 16, axis=1)
    Image.fromarray(pixels, "RGB").save(path, "JPEG", quality=92)
    assert path.is_file()
    return str(path)


@dataclass
class SyntheticWorld:
    wp: ThreadingHTTPServer
    studio_server: ThreadingHTTPServer
    state: FakeWordPressState
    base: str
    token: str
    source_a: str
    source_b: str
    catalog: list[tuple[str, str]]

    def api(self, method: str, path: str, payload=None):
        response = requests.request(
            method,
            self.base + path,
            json=payload,
            headers={
                "Authorization": "Bearer " + self.token,
                "Origin": self.base,
            },
            timeout=35,
        )
        return response, response.json()

    def plan(self):
        response, payload = self.api("POST", "/studio/plan", {"url": PUBLIC_URL, "count": 2})
        assert response.status_code == 200, payload
        assert payload["status"] == "success"
        return payload

    def apply(self, plan_id: str, candidate_ids: list[str], confirm_paid=False):
        return self.api(
            "POST",
            "/studio/apply",
            {"plan_id": plan_id, "accepted_ids": candidate_ids, "confirm_paid": confirm_paid},
        )

    def await_job(self, job_id: str):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            response, result = self.api("GET", "/jobs/" + job_id)
            assert response.status_code == 200, result
            job = result["job"]
            if job["status"] in {"success", "failed", "partial", "interrupted"}:
                return job
            time.sleep(0.10)
        pytest.fail("Synthetic WordPress job did not reach a terminal state")


@pytest.fixture
def world(tmp_path, monkeypatch):
    state = FakeWordPressState()
    wp, wp_thread = _start_server(FakeWordPressHandler, state=state)
    app = None
    app_thread = None
    try:
        wp_origin = f"http://127.0.0.1:{wp.server_port}"

        # A configured HTTPS permalink is still mandatory for Studio. Only
        # authenticated WordPress REST transport is redirected to this loopback
        # instance; no application HTTP or publisher methods are mocked.
        monkeypatch.setattr(wordpress.YOWordPressUploader, "SITE_ENDPOINTS", {
            "synthetic": {
                "url": "https://synthetic.pictova.invalid",
                "user": "pictova-test-user",
                "password": "pictova-test-password",
            }
        })
        original_init = wordpress.YOWordPressUploader.__init__

        def loopback_uploader(self, site="synthetic"):
            original_init(self, site=site)
            self.base_url = wp_origin

        monkeypatch.setattr(wordpress.YOWordPressUploader, "__init__", loopback_uploader)
        monkeypatch.setenv("PICTOVA_POST_MANIFEST_DIR", str(tmp_path / "manifests"))
        monkeypatch.setenv("PICTOVA_OPERATION_RECEIPT_DIR", str(tmp_path / "receipts"))
        monkeypatch.setattr(attach, "_ATTACH_LOCK_DIR", tmp_path / "locks")

        original_processor = YOImageProcessor
        monkeypatch.setattr(
            processor, "YOImageProcessor",
            lambda work_dir=None: original_processor(work_dir=tmp_path / "work"),
        )
        monkeypatch.setattr(metadata, "_db_cached_metadata", lambda path: None)
        monkeypatch.setattr(metadata, "has_any_vision_source", lambda: True)

        def synthetic_vision(image_path, location_hint, post_context):
            # Preserve the unprimed vision contract. Only the external
            # provider's response is synthetic; metadata policy is real.
            assert location_hint == "" and post_context == {}
            name = Path(image_path).name
            place = HEADING_B if "avanos" in name else HEADING_A
            return {
                "title": place + " kaya ve taş yüzey ayrıntıları",
                "alt": place + " çevresindeki taş yapıların dış cephesi",
                "description": place + " yapılarının belirgin dış cephe görünümü",
                "keywords": place.split() + ["taş", "yapı"],
                "scene": "castle" if place == HEADING_A else "workshop",
                "activity": "sightseeing",
                "source": "synthetic_vision",
            }

        monkeypatch.setattr(metadata, "analyze_image_vision_chain", synthetic_vision)

        source_a = _source_photo(tmp_path / "uchisar.jpg", 77)
        source_b = _source_photo(tmp_path / "avanos.jpg", 81)
        catalog = [(source_a, HEADING_A), (source_b, HEADING_B)]

        # Test boundary: a deterministic *discovery provider* supplies real
        # local JPEGs. The full native planner, processor, vision adapter,
        # quality gate, publisher and WordPress read/write paths run normally.
        def synthetic_discovery(**kwargs):
            assert kwargs["source"] == "auto"
            assert kwargs["post_context"]["slug"] == SLUG
            files = [value for value, _heading in catalog]
            assignments = {
                value: {"text": heading, "level": 2}
                for value, heading in catalog
            }
            return {
                "source": "synthetic_local_discovery",
                "files": files,
                "heading_assignments": assignments,
                "warnings": [],
            }

        monkeypatch.setattr(attach, "resolve_source_images", synthetic_discovery)
        plans = studio.StudioPlans()
        registry = JobRegistry(directory=tmp_path / "jobs")
        monkeypatch.setattr(studio, "job_registry", registry)
        monkeypatch.setattr(studio, "studio_plans", plans)
        monkeypatch.setattr(app_server, "job_registry", registry)
        monkeypatch.setattr(app_server, "studio_plans", plans)

        app = app_server.serve(host="127.0.0.1", port=0, token_override=TOKEN)
        app_thread = threading.Thread(target=app.serve_forever, daemon=True)
        app_thread.start()
        yield SyntheticWorld(
            wp=wp, studio_server=app, state=state,
            base=f"http://127.0.0.1:{app.server_port}",
            token=TOKEN, source_a=source_a, source_b=source_b, catalog=catalog,
        )
    finally:
        if app:
            app.shutdown()
            app.server_close()
        if app_thread:
            app_thread.join(timeout=5)
        wp.shutdown()
        wp.server_close()
        wp_thread.join(timeout=5)


def _assert_untouched_article(state):
    assert state.post_content == ARTICLE
    assert "<!-- wp:image" not in state.post_content


def _assert_verified_gutenberg(world, job, heading):
    result = job["result"]
    assert job["status"] == "success", result
    assert result["status"] == "success"
    assert result["inserted_blocks"] == 1
    assert result["publish_reason"] == "verified_post_update"
    assert result["needs_reconciliation"] is False
    media_ids = result["uploaded_media_ids"]
    assert len(media_ids) == 1
    item = world.state.media[media_ids[0]]
    assert item["post"] == POST_ID
    assert item["bytes"][:4] == b"RIFF" and item["bytes"][8:12] == b"WEBP"
    assert item["metadata"]["title"]
    assert item["metadata"]["alt_text"]
    assert item["metadata"]["description"]
    assert "<!-- wp:image" in world.state.post_content
    assert "Sentetik Kapadokya yazısının orijinal giriş paragrafı." in world.state.post_content
    assert "Avanos hakkında korunan editör metni." in world.state.post_content
    found = media_items_from_content(world.state.post_content)
    assert len(found) == 1
    assert found[0]["media_id"] == media_ids[0]
    assert found[0]["heading"] == heading
    assert found[0]["heading_level"] == 2
    manifest = load_post_media_manifest("synthetic", POST_ID)
    assert manifest["expected_media_ids"] == media_ids
    assert assess_post_media(manifest, world.state.post_content)["state"] == "healthy"
    assert Path(result["receipt_path"]).is_file()
    return media_ids[0]


def test_studio_full_http_publish_verifies_real_webp_wp_blocks_and_manifest(world):
    plan = world.plan()
    assert len(plan["candidates"]) == 2
    assert {item["heading"] for item in plan["candidates"]} == {HEADING_A, HEADING_B}
    assert all(item["available"] and item["local_preview"] for item in plan["candidates"])
    chosen = next(item for item in plan["candidates"] if item["heading"] == HEADING_A)
    rejected = next(item for item in plan["candidates"] if item["heading"] == HEADING_B)
    preview = requests.get(
        world.base + f"/studio/preview?plan={plan['plan_id']}&candidate={chosen['id']}",
        headers={"Authorization": "Bearer " + world.token},
        timeout=10,
    )
    assert preview.status_code == 200
    with Image.open(BytesIO(preview.content)) as image:
        assert image.format == "JPEG"
        assert image.width > 0
    response, accepted = world.apply(plan["plan_id"], [chosen["id"]])
    assert response.status_code == 202, accepted
    job = world.await_job(accepted["job_id"])
    media_id = _assert_verified_gutenberg(world, job, HEADING_A)
    assert rejected["id"] not in world.state.post_content
    assert len(world.state.media) == 1
    assert [path for verb, path in world.state.calls if verb == "POST"].count(
        "/wp-json/wp/v2/media"
    ) == 1
    assert ("POST", f"/wp-json/wp/v2/posts/{POST_ID}") in world.state.calls
    # Explicit one-use plan: no duplicate license/upload or content edit.
    refused, payload = world.apply(plan["plan_id"], [chosen["id"]])
    assert refused.status_code == 400
    assert payload["status"] == "failed"
    assert list(world.state.media) == [media_id]


def test_synthetic_wordpress_post_update_failure_rolls_back_uploaded_media(world):
    original = world.state.post_content
    plan = world.plan()
    world.state.denied_post_update = True
    chosen = plan["candidates"][0]
    response, accepted = world.apply(plan["plan_id"], [chosen["id"]])
    assert response.status_code == 202, accepted
    job = world.await_job(accepted["job_id"])
    assert job["status"] == "failed", job
    assert job["result"]["status"] == "failed"
    assert job["result"]["inserted_blocks"] == 0
    assert job["result"]["rollback"]["attempted"] is True
    assert job["result"]["rollback"]["deleted_media_ids"] == [901]
    assert ("DELETE", "/wp-json/wp/v2/media/901") in world.state.calls
    assert world.state.post_content == original
    assert world.state.media == {}
    assert load_post_media_manifest("synthetic", POST_ID) is None


def test_synthetic_wordpress_readback_rejects_false_success_and_rolls_back(world):
    plan = world.plan()
    world.state.suppress_inserted_blocks = True
    response, accepted = world.apply(plan["plan_id"], [plan["candidates"][0]["id"]])
    assert response.status_code == 202, accepted
    job = world.await_job(accepted["job_id"])
    assert job["status"] == "partial", job
    result = job["result"]
    assert result["status"] == "partial"
    assert result["publish_reason"] == "post_update_verification_failed"
    assert result["needs_reconciliation"] is True
    assert result["inserted_blocks"] == 0
    assert result["rollback"]["deleted_media_ids"] == [901]
    assert world.state.media == {}
    _assert_untouched_article(world.state)
    assert load_post_media_manifest("synthetic", POST_ID) is None


def test_synthetic_wordpress_edited_after_preview_blocks_before_media_write(world):
    plan = world.plan()
    with world.state.lock:
        world.state.post_content += "\n<!-- wp:paragraph --><p>Editör yeni notu.</p><!-- /wp:paragraph -->"
        world.state.modified_revision += 1
    response, accepted = world.apply(plan["plan_id"], [plan["candidates"][0]["id"]])
    assert response.status_code == 202, accepted
    job = world.await_job(accepted["job_id"])
    assert job["status"] == "failed", job
    assert "changed since Studio preview" in job["result"]["warnings"][0]
    assert world.state.media == {}
    assert not any(path == "/wp-json/wp/v2/media" for _, path in world.state.calls)
    assert load_post_media_manifest("synthetic", POST_ID) is None


def test_synthetic_paid_studio_requires_consent_and_never_calls_paid_network(world, monkeypatch):
    from src.pictova.engine import selector
    from src.pictova.providers import deposit

    preview_url = "https://synthetic-preview.pictova.invalid/license-991.jpg"
    world.catalog[:] = [(preview_url, HEADING_A)]
    monkeypatch.setattr(selector, "_DEPOSIT_DISCOVERY_CACHE", {
        ("Uchisar Castle", 20): [{
            "id": "991", "title": "Uçhisar Kalesi", "preview_url": preview_url,
        }]
    })
    login = []
    licensed = []

    def fake_login():
        login.append(True)
        return "synthetic-license-session"

    def fake_download(asset_id, session_id):
        licensed.append((asset_id, session_id))
        return world.source_a

    monkeypatch.setattr(deposit, "_login", fake_login)
    monkeypatch.setattr(deposit, "download", fake_download)
    plan = world.plan()
    chosen = plan["candidates"][0]
    assert chosen["paid"] is True
    refused, detail = world.apply(plan["plan_id"], [chosen["id"]], confirm_paid=False)
    assert refused.status_code == 400 and detail["status"] == "failed"
    assert login == [] and licensed == []
    response, accepted = world.apply(plan["plan_id"], [chosen["id"]], confirm_paid=True)
    assert response.status_code == 202, accepted
    job = world.await_job(accepted["job_id"])
    _assert_verified_gutenberg(world, job, HEADING_A)
    assert len(login) == 1
    assert licensed == [("991", "synthetic-license-session")]
