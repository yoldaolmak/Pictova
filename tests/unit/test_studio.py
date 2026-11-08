"""Studio regression tests: exact candidate approval, local privacy and HTTP controls."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import threading
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

from PIL import Image
import pytest

from src.pictova.app import server as http
from src.pictova.app import studio
from src.pictova.engine import attach as engine


TEST_TOKEN = "studio-unit-test-token-at-least-thirty-two-characters"


def _ctx():
    return {
        "id": 71,
        "slug": "kapadokya-gezilecek-yerler",
        "title": "Kapadokya Gezilecek Yerler",
        "modified": "2026-11-07T13:00:00",
        "content_raw": "<h2>Uçhisar Kalesi</h2><h2>Avanos Çömlekçiliği</h2>",
        "available_headings": [
            {"text": "Uçhisar Kalesi", "level": 2},
            {"text": "Avanos Çömlekçiliği", "level": 2},
        ],
    }


def _photo(tmp_path, name):
    image = tmp_path / name
    Image.new("RGB", (280, 170), (52, 105, 131)).save(image)
    return str(image)


def _plan_result(files):
    context = _ctx()
    headings = context["available_headings"]
    return {
        "status": "success",
        "selection": {
            "source": "auto",
            "files": files,
            "heading_assignments": {file: dict(headings[index % len(headings)]) for index, file in enumerate(files)},
            "warnings": [],
        },
        "warnings": [],
    }


def _make_plan(store, monkeypatch, files):
    monkeypatch.setattr(studio, "_resolve_wordpress_url", lambda url: ("yoldaolmak", 71, _ctx()))
    monkeypatch.setattr(studio, "plan_attach", lambda request: _plan_result(files))
    return store.plan("https://yoldaolmak.com/kapadokya-gezilecek-yerler.html", count=4)


def test_url_resolution_accepts_configured_wp_permalink_only(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return [{"id": 71, "slug": "kapadokya-gezilecek-yerler"}]

    class StubUploader:
        SITE_ENDPOINTS = {"yoldaolmak": {"url": "https://yoldaolmak.com"}}

        def __init__(self, site):
            assert site == "yoldaolmak"
            self.base_url = "https://yoldaolmak.com"
            self.session = MagicMock()
            self.session.get.return_value = Response()
            StubUploader.last_session = self.session

    monkeypatch.setattr(studio, "YOWordPressUploader", StubUploader)
    monkeypatch.setattr(studio, "fetch_post_context", lambda post_id, site: _ctx())
    site, post_id, post = studio._resolve_wordpress_url(
        "https://www.yoldaolmak.com/kapadokya-gezilecek-yerler.html?utm_source=x"
    )
    assert site == "yoldaolmak" and post_id == 71
    assert post["title"] == "Kapadokya Gezilecek Yerler"
    call = StubUploader.last_session.get.call_args
    assert call.args[0] == "https://yoldaolmak.com/wp-json/wp/v2/posts"
    assert call.kwargs["params"]["slug"] == "kapadokya-gezilecek-yerler"
    assert call.kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/kapadokya.html",
        "http://yoldaolmak.com/kapadokya.html",
        "https://yoldaolmak.com.evil.example/kapadokya.html",
        "https://u:p@yoldaolmak.com/kapadokya.html",
        "https://yoldaolmak.com:8443/kapadokya.html",
        "https://yoldaolmak.com/wp-json/wp/v2/posts",
        "https://yoldaolmak.com/../",
        "file:///home/user/photo.jpg",
    ],
)
def test_studio_refuses_unconfigured_url_before_network(monkeypatch, url):
    monkeypatch.setattr(studio.YOWordPressUploader, "SITE_ENDPOINTS", {"yoldaolmak": {"url": "https://yoldaolmak.com"}})
    with patch.object(studio.YOWordPressUploader, "__init__", side_effect=AssertionError("No WP network")):
        with pytest.raises(studio.StudioError):
            studio._resolve_wordpress_url(url)


def test_plan_discloses_only_candidate_ids_and_generates_actual_local_thumbnail(tmp_path, monkeypatch):
    a = _photo(tmp_path, "uchisar.jpg")
    b = _photo(tmp_path, "avanos.jpg")
    store = studio.StudioPlans()
    result = _make_plan(store, monkeypatch, [a, b])
    assert result["status"] == "success"
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["heading"] == "Uçhisar Kalesi"
    assert result["candidates"][0]["available"] is True
    assert result["candidates"][0]["local_preview"] is True
    assert a not in json.dumps(result), "No private absolute paths in the browser plan"
    blob = store.preview(result["plan_id"], result["candidates"][0]["id"])
    assert blob.startswith(b"\xff\xd8")
    with Image.open(BytesIO(blob)) as image:
        assert image.size == (280, 170)


def test_studio_approves_only_checked_images_and_preserves_heading_identity(tmp_path, monkeypatch):
    a = _photo(tmp_path, "uchisar.jpg")
    b = _photo(tmp_path, "avanos.jpg")
    store = studio.StudioPlans()
    plan = _make_plan(store, monkeypatch, [a, b])
    selected = plan["candidates"][1]["id"]
    jobs = []

    def fake_create_job(*, kind, payload, runner):
        jobs.append((kind, payload, runner))
        return {"job_id": "synthetic-job-1"}

    monkeypatch.setattr(studio.job_registry, "create_job", fake_create_job)
    accepted = store.approve(plan["plan_id"], [selected])
    assert accepted["selected_count"] == 1 and accepted["status"] == "accepted"
    assert jobs[0][0] == "studio_attach"
    assert jobs[0][1] == {"site": "yoldaolmak", "post_id": 71, "selected_count": 1}
    monkeypatch.setattr(
        studio,
        "prepare_attach_request",
        lambda **kwargs: (
            dict(kwargs),
            _ctx(),
            {"language": "tr", "people_first": False},
        ),
    )
    monkeypatch.setattr(studio, "validate_attach_request", lambda **kwargs: None)
    monkeypatch.setattr(studio, "_finish_attach_job", lambda result: result)

    def attach_stub(**kwargs):
        selected_assets = kwargs["selection_loader"]()
        assert selected_assets["files"] == [b]
        assert selected_assets["heading_assignments"][b]["text"] == "Avanos Çömlekçiliği"
        assert kwargs["expected_post_digest"] == studio._fingerprint(_ctx())
        return {"status": "success", "selected_assets": selected_assets["files"]}

    monkeypatch.setattr(studio, "execute_native_attach", attach_stub)
    result = jobs[0][2](jobs[0][1])
    assert result["selected_assets"] == [b]
    with pytest.raises(studio.StudioError, match="expired|kullanıldı|süresi"):
        store.approve(plan["plan_id"], [selected])


def test_file_change_after_review_blocks_approved_selection(tmp_path, monkeypatch):
    a = _photo(tmp_path, "uchisar.jpg")
    store = studio.StudioPlans()
    plan = _make_plan(store, monkeypatch, [a])
    entry = plan["candidates"][0]
    Path(a).write_bytes(b"tampered")
    with pytest.raises(studio.StudioError, match="değişti"):
        store.preview(plan["plan_id"], entry["id"])

    jobs = []
    monkeypatch.setattr(studio.job_registry, "create_job", lambda **kwargs: (jobs.append(kwargs) or {"job_id": "a"}))
    store.approve(plan["plan_id"], [entry["id"]])
    monkeypatch.setattr(studio, "prepare_attach_request", lambda **kwargs: (dict(kwargs), _ctx(), {}))
    monkeypatch.setattr(studio, "validate_attach_request", lambda **kwargs: None)

    def no_wordpress(**kwargs):
        with pytest.raises(studio.StudioError, match="değişti"):
            kwargs["selection_loader"]()
        return {"status": "failed"}

    monkeypatch.setattr(studio, "execute_native_attach", no_wordpress)
    monkeypatch.setattr(studio, "_finish_attach_job", lambda result: result)
    assert jobs[0]["runner"]({})["status"] == "failed"


def test_unlisted_duplicate_or_empty_candidate_ids_cannot_trigger_attach(tmp_path, monkeypatch):
    a = _photo(tmp_path, "uchisar.jpg")
    store = studio.StudioPlans()
    p = _make_plan(store, monkeypatch, [a])
    id_ = p["candidates"][0]["id"]
    monkeypatch.setattr(studio.job_registry, "create_job", lambda **kw: pytest.fail("unexpected job"))
    for invalid in ([], ["unknown"], [id_, id_], [1]):
        with pytest.raises(studio.StudioError):
            store.approve(p["plan_id"], invalid)


def test_paid_preview_requires_distinct_license_consent(tmp_path, monkeypatch):
    preview = "https://preview.example.test/exact-stock.jpg"
    cache = {
        ("Uchisar Castle", 20): [
            {"id": "53148", "title": "Uchisar Castle", "preview_url": preview},
        ]
    }
    from src.pictova.engine import selector

    monkeypatch.setattr(selector, "_DEPOSIT_DISCOVERY_CACHE", cache)
    store = studio.StudioPlans()
    plan = _make_plan(store, monkeypatch, [preview])
    asset = plan["candidates"][0]
    assert asset["paid"] is True and asset["available"] is True
    with pytest.raises(studio.StudioError, match="Lisanslı"):
        store.approve(plan["plan_id"], [asset["id"]])

    jobs = []
    monkeypatch.setattr(
        studio.job_registry, "create_job", lambda **kwargs: (jobs.append(kwargs) or {"job_id": "paid-job"})
    )
    assert store.approve(plan["plan_id"], [asset["id"]], confirm_paid=True)["status"] == "accepted"

    monkeypatch.setattr(studio, "prepare_attach_request", lambda **kwargs: (dict(kwargs), _ctx(), {}))
    monkeypatch.setattr(studio, "validate_attach_request", lambda **kwargs: None)
    monkeypatch.setattr(studio, "_finish_attach_job", lambda result: result)
    licensed = _photo(tmp_path, "licensed.jpg")
    from src.pictova.providers import deposit

    monkeypatch.setattr(deposit, "_login", lambda: "fake-session")
    downloads = []

    def fake_download(id_, session):
        downloads.append((id_, session))
        return licensed

    monkeypatch.setattr(deposit, "download", fake_download)

    def attach_stub(**kwargs):
        chosen = kwargs["selection_loader"]()
        assert chosen["files"] == [licensed]
        assert chosen["heading_assignments"][licensed]["text"] == "Uçhisar Kalesi"
        return {"status": "success"}

    monkeypatch.setattr(studio, "execute_native_attach", attach_stub)
    assert jobs[0]["runner"]({})["status"] == "success"
    assert downloads == [("53148", "fake-session")]


def test_post_changed_after_preview_rejected_before_paid_selection(monkeypatch):
    callback = MagicMock(side_effect=AssertionError("No paid download on changed post"))
    monkeypatch.setattr(
        engine,
        "fetch_post_context",
        lambda post_id, site: {
            **_ctx(),
            "modified": "2026-11-07T15:30:00",
        },
    )
    result = engine._execute_native_attach_locked(
        site="yoldaolmak",
        request={"post_id": 71, "count": 1},
        post_context=_ctx(),
        constraints={},
        selection_loader=callback,
        expected_post_digest=studio._fingerprint(_ctx()),
    )
    assert result["status"] == "failed"
    assert "changed" in result["warnings"][0]
    callback.assert_not_called()


def test_http_studio_static_host_and_origin_guards(monkeypatch):
    srv = http.serve(host="127.0.0.1", port=0, token_override=TEST_TOKEN)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = srv.server_address
        address = "http://" + host + ":" + str(port)
        with urlopen(address + "/studio", timeout=3) as page:
            data = page.read()
            assert page.status == 200
            assert b"PICTOVA" in data
            assert TEST_TOKEN.encode() not in data
            assert b"frame-ancestors 'none'" in page.headers["Content-Security-Policy"].encode()
        bad_host = Request(address + "/studio", headers={"Host": "attacker.example"})
        with pytest.raises(HTTPError) as error:
            urlopen(bad_host, timeout=3)
        assert error.value.code == 400

        monkeypatch.setattr(
            http.studio_plans,
            "plan",
            lambda url, count: {
                "status": "success",
                "plan_id": "no-secret",
                "post": {"title": "Test"},
                "candidates": [],
            },
        )

        def post(origin=None, token=TEST_TOKEN):
            headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
            if origin:
                headers["Origin"] = origin
            req = Request(
                address + "/studio/plan",
                data=json.dumps({"url": "https://yoldaolmak.com/a.html", "count": 1}).encode(),
                headers=headers,
                method="POST",
            )
            try:
                with urlopen(req, timeout=3) as result:
                    return result.status
            except HTTPError as error:
                return error.code

        assert post(origin="https://attacker.example") == 403
        assert post(token="bad") == 401
        assert post(origin=address) == 200
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=3)


def test_failed_job_enqueue_restores_studio_plan(tmp_path, monkeypatch):
    local_photo = _photo(tmp_path, "uchisar.jpg")
    store = studio.StudioPlans()
    plan = _make_plan(store, monkeypatch, [local_photo])
    candidate_id = plan["candidates"][0]["id"]

    monkeypatch.setattr(studio.job_registry, "create_job", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(studio.StudioError, match="kuyruğa alınamadı"):
        store.approve(plan["plan_id"], [candidate_id])

    retained = store._plans[plan["plan_id"]]
    assert retained["used"] is False
    assert retained["status"] == "available"

    monkeypatch.setattr(studio.job_registry, "create_job", lambda **kwargs: {"job_id": "recovered"})
    assert store.approve(plan["plan_id"], [candidate_id])["job_id"] == "recovered"
    assert retained["used"] is True


def test_concurrent_studio_approval_cannot_enqueue_twice(tmp_path, monkeypatch):
    local_photo = _photo(tmp_path, "uchisar.jpg")
    store = studio.StudioPlans()
    plan = _make_plan(store, monkeypatch, [local_photo])
    candidate_id = plan["candidates"][0]["id"]
    entering = threading.Event()
    releasing = threading.Event()
    jobs = []
    errors = []

    def slow_create_job(**kwargs):
        jobs.append(kwargs)
        entering.set()
        assert releasing.wait(3)
        return {"job_id": "only-job"}

    monkeypatch.setattr(studio.job_registry, "create_job", slow_create_job)

    def first():
        try:
            store.approve(plan["plan_id"], [candidate_id])
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert entering.wait(3)
        with pytest.raises(studio.StudioError, match="zaten uygulamaya"):
            store.approve(plan["plan_id"], [candidate_id])
    finally:
        releasing.set()
        thread.join(timeout=3)

    assert not errors
    assert len(jobs) == 1



def test_review_candidate_keeps_local_identity_private_and_rejects_unverified_sources(tmp_path):
    valid = {("Uçhisar Kalesi", 2)}
    heading = {"text": "Uçhisar Kalesi", "level": 2}
    local = _photo(tmp_path, "uchisar.jpg")

    assert studio._review_candidate(local, None, "plan-1", valid) is None
    assert studio._review_candidate(local, {"text": "Other heading", "level": 2}, "plan-1", valid) is None
    assert studio._review_candidate(42, heading, "plan-1", valid) is None

    identity, private, public = studio._review_candidate(local, heading, "plan-1", valid)
    assert private["path"] == local
    assert "identity" in private
    assert public["id"] == identity
    assert public["heading"] == "Uçhisar Kalesi"
    assert public["local_preview"] is True
    assert public["available"] is True
    assert public["preview_url"] == ""
    assert local not in json.dumps(public)
    assert local not in public.values()

    missing_id, missing, missing_public = studio._review_candidate(
        str(tmp_path / "missing.jpg"), heading, "plan-1", valid
    )
    assert missing_id and missing["enabled"] is False
    assert missing_public["available"] is False
    assert missing_public["local_preview"] is False

    icloud_id, icloud, icloud_public = studio._review_candidate("icloud://photo", heading, "plan-1", valid)
    assert icloud_id and icloud["enabled"] is False
    assert icloud_public["source"] == "icloud"
    assert icloud_public["paid"] is False

    remote_id, remote, remote_public = studio._review_candidate(
        "https://untrusted.invalid/unlisted.jpg", heading, "plan-1", valid
    )
    assert remote_id and remote["enabled"] is False
    assert remote_public["paid"] is False
    assert remote_public["preview_url"] == ""


def test_approved_selection_validates_source_identity_before_posting(tmp_path):
    original = _photo(tmp_path, "source.jpg")
    first = {"path": original, "identity": studio._file_identity(original), "heading": {"text": "Uçhisar", "level": 2}}
    result = studio._load_approved_selection([first])
    assert result["files"] == [original]
    assert result["heading_assignments"][original] == {"text": "Uçhisar", "level": 2}

    Path(original).write_bytes(b"changed after review")
    with pytest.raises(studio.StudioError, match="değişti"):
        studio._load_approved_selection([first])


def test_approved_selection_reuses_paid_session_and_rejects_duplicate_download_paths(tmp_path, monkeypatch):
    from src.pictova.providers import deposit

    one = _photo(tmp_path, "one.jpg")
    two = _photo(tmp_path, "two.jpg")
    logins = []
    downloads = []

    def fake_login():
        logins.append("session")
        return "fake-session"

    def fake_download(asset_id, session):
        downloads.append((asset_id, session))
        return {"11": one, "22": two}[asset_id]

    monkeypatch.setattr(deposit, "_login", fake_login)
    monkeypatch.setattr(deposit, "download", fake_download)
    chosen = [
        {"deposit_id": "11", "heading": {"text": "Uçhisar", "level": 2}},
        {"deposit_id": "22", "heading": {"text": "Avanos", "level": 2}},
    ]
    result = studio._load_approved_selection(chosen)
    assert result["files"] == [one, two]
    assert downloads == [("11", "fake-session"), ("22", "fake-session")]
    assert logins == ["session"]

    monkeypatch.setattr(deposit, "download", lambda asset_id, session: one)
    with pytest.raises(studio.StudioError, match="iki kez"):
        studio._load_approved_selection(chosen)
