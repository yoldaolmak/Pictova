"""Explicit state transition contracts for publishing, jobs, scan leases and media."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from unittest.mock import MagicMock

import pytest

from src.pictova.engine.publish_outcome import classify_job_result, classify_publish_result
from src.services.post_media_guard import assess_post_media
from src.services.wordpress import YOWordPressUploader


def _post(heading="Uçhisar Kalesi", *, url="https://example.test/71.webp", media_id=71):
    return (
        '<!-- wp:heading {"level":2} --><h2>' + heading + '</h2><!-- /wp:heading -->'
        '<!-- wp:image {"id":' + str(media_id) + '} -->'
        '<figure><img src="' + url + '" class="wp-image-' + str(media_id) + '" alt="Kale"/></figure>'
        '<!-- /wp:image -->'
    )


def test_publish_results_require_verified_gutenberg_content():
    clean = {"uploaded": [{"media_id": 71}], "failed": [],
             "content_update": {"success": True, "updated": True, "inserted": 1}}
    assert classify_publish_result(clean) == ("success", "verified_post_update", False)
    assert classify_publish_result(clean, warnings=True)[0] == "partial"
    assert classify_publish_result({**clean, "failed": ["second failed"]})[0] == "partial"

    failed = {**clean, "content_update": {
        "success": False, "code": "heading_insertion_failed", "inserted": 0,
    }}
    assert classify_publish_result(failed) == ("failed", "heading_insertion_failed", False)
    assert classify_publish_result({**clean, "content_update": {
        "success": True, "updated": False, "inserted": 0,
    }}) == ("failed", "no_verified_media_placement", False)
    assert classify_publish_result({"uploaded": [{"media_id": 71}]}) == (
        "failed", "missing_content_update", True
    )

    for code in ("media_manifest_write_failed", "post_update_verification_failed"):
        uncertain = {**failed, "content_update": {"success": False, "code": code}}
        assert classify_publish_result(uncertain) == ("partial", code, True)

    replay = {"uploaded": [], "skipped": [{"media_id": 71}],
              "content_update": {"success": True, "idempotent": True, "inserted": 0}}
    assert classify_publish_result(replay) == ("success", "already_present", False)
    assert classify_publish_result({"uploaded": [], "skipped": [], "content_update": replay["content_update"]})[0] == "failed"


@pytest.mark.parametrize(("source", "expected"), [
    ("ok", "success"), ("success", "success"), ("local", "success"),
    ("partial", "partial"), ("failed", "failed"), ("drift", "failed"),
    ("skipped", "failed"), ("warning", "failed"), ("unknown", "failed"),
])
def test_job_terminal_mapping_is_not_a_lossy_boolean(source, expected):
    assert classify_job_result(source) == expected


def test_native_attach_result_uses_actual_wordpress_commit(monkeypatch):
    from src.pictova.engine import attach as eng

    context = {"title": "Uçhisar", "available_headings": [{"text": "Uçhisar Kalesi", "level": 2}]}
    monkeypatch.setattr(eng, "resolve_source_images", lambda **kw: {
        "files": ["/tmp/photo.jpg"],
        "heading_assignments": {"/tmp/photo.jpg": {"text": "Uçhisar Kalesi", "level": 2}},
        "warnings": [],
    })
    monkeypatch.setattr(eng, "process_selected_images", lambda files: {
        "processed_images": ["/tmp/photo.webp"],
        "processed_details": {"/tmp/photo.webp": {"input": "/tmp/photo.jpg"}},
        "panoramic_images": {}, "failed_images": [], "work_dir": "/tmp",
    })
    monkeypatch.setattr(eng, "build_native_metadata_map", lambda *args, **kwargs: (
        {"/tmp/photo.webp": {"title": "Uçhisar Kalesi"}}, []
    ))
    monkeypatch.setattr(eng, "quality_gate_native_batch", lambda **kw: (
        ["/tmp/photo.webp"], {"/tmp/photo.webp": {"title": "Uçhisar Kalesi"}},
        {"/tmp/photo.webp": {"input": "/tmp/photo.jpg"}}, []
    ))
    monkeypatch.setattr(eng, "finalize_publish_assets", lambda **kw: (
        kw["processed_images"], kw["metadata_dict"], kw["processed_details"]
    ))
    monkeypatch.setattr(eng, "publish_processed_images", lambda **kw: {
        "uploaded": [{"media_id": 71}], "failed": [],
        "content_update": {"success": False, "code": "heading_insertion_failed", "inserted": 0},
    })
    failure = eng._execute_native_attach_locked(
        site="yoldaolmak", request={"post_id": 71, "count": 1, "source": "auto"},
        post_context=context, constraints={},
    )
    assert failure["status"] == "failed"
    assert failure["inserted_blocks"] == 0
    assert failure["publish_reason"] == "heading_insertion_failed"

    monkeypatch.setattr(eng, "publish_processed_images", lambda **kw: {
        "uploaded": [{"media_id": 71}], "failed": [],
        "content_update": {"success": True, "updated": True, "inserted": 1},
    })
    success = eng._execute_native_attach_locked(
        site="yoldaolmak", request={"post_id": 71, "count": 1, "source": "auto"},
        post_context=context, constraints={},
    )
    assert success["status"] == "success"
    assert success["inserted_blocks"] == 1


def test_manifest_detects_moved_replaced_or_duplicate_media():
    expected = {
        "expected_media_ids": [71],
        "media_items": [{
            "media_id": 71, "url": "https://example.test/71.webp",
            "heading": "Uçhisar Kalesi", "heading_level": 2,
        }],
    }
    content = _post()
    assert assess_post_media(expected, content)["state"] == "healthy"

    moved = _post("Avanos Çömlekçiliği")
    misplaced = assess_post_media(expected, moved)
    assert misplaced["state"] == "drift"
    assert misplaced["misplaced_media_ids"] == [71]
    assert misplaced["missing_media_ids"] == []

    replaced = assess_post_media(expected, _post(url="https://example.test/other.webp"))
    assert replaced["changed_url_media_ids"] == [71]

    duplicate = assess_post_media(expected, content + _post())
    assert duplicate["state"] == "drift"
    assert duplicate["duplicate_media_ids"] == [71]

    fake = assess_post_media(expected, '<p>wp-image-71 but no Gutenberg image</p>')
    assert fake["state"] == "drift"
    assert fake["missing_media_ids"] == [71]


def test_verified_post_content_requires_exact_heading_before_manifest(monkeypatch):
    uploader = object.__new__(YOWordPressUploader)
    uploader.site = "yoldaolmak"
    manifest = MagicMock(side_effect=AssertionError("must not write a false healthy manifest"))
    monkeypatch.setattr("src.services.wordpress.save_post_media_manifest", manifest)
    result = uploader._record_verified_media(
        post_id=71,
        post={"content_raw": _post("Different Place"), "modified": "2026-11-07"},
        media_items=[{
            "media_id": 71, "url": "https://example.test/71.webp",
            "heading": "Uçhisar Kalesi", "heading_level": 2,
        }],
        updated=True, inserted=1, removed_broken=0,
    )
    assert result["success"] is False
    assert result["code"] == "post_update_verification_failed"
    manifest.assert_not_called()


def test_guard_repair_repositions_misplaced_media(monkeypatch, tmp_path):
    from src.services.post_media_guard import save_post_media_manifest

    monkeypatch.setenv("PICTOVA_POST_MANIFEST_DIR", str(tmp_path))
    save_post_media_manifest(
        site="yoldaolmak", post_id=71,
        media_items=[{"media_id": 71, "url": "https://example.test/71.webp",
                      "heading": "Uçhisar Kalesi", "heading_level": 2}],
        content_raw=_post(),
    )
    uploader = object.__new__(YOWordPressUploader)
    uploader.site = "yoldaolmak"
    uploader.fetch_post_context = MagicMock(return_value={"content_raw": _post("Other Heading")})
    uploader.append_media_to_post_content = MagicMock(return_value={"success": False, "code": "mixed_media_ownership"})
    result = uploader.guard_post_media(71, repair=True)
    assert result["state"] == "drift" and result["status"] == "failed"
    kwargs = uploader.append_media_to_post_content.call_args.kwargs
    assert kwargs["allow_manifest_repair"] is True
    assert kwargs["reposition_managed"] is True


def test_job_receipt_survives_restart_without_raw_media_paths(tmp_path):
    from src.pictova.app.state import JobRegistry

    reg = JobRegistry(directory=tmp_path)
    finished = threading.Event()

    def runner(_payload):
        finished.set()
        return {
            "status": "partial", "inserted_blocks": 1,
            "warnings": ["some candidates blocked"],
            "raw": {"private_photo_path": "/Users/private/Mac Photos/secret.jpg"},
        }

    job = reg.create_job(
        kind="studio_attach",
        payload={"site": "yoldaolmak", "post_id": 71, "secret": "never_saved"},
        runner=runner,
    )
    assert finished.wait(5)
    deadline = threading.Event()
    for _ in range(500):
        latest = reg.get_job(job["job_id"])
        if latest["status"] == "partial":
            break
        deadline.wait(0.01)
    assert latest["status"] == "partial"
    receipt = tmp_path / f"{job['job_id']}.json"
    assert receipt.exists()
    text = receipt.read_text(encoding="utf-8")
    assert "private_photo_path" not in text and "never_saved" not in text
    assert receipt.stat().st_mode & 0o777 == 0o600

    restored = JobRegistry(directory=tmp_path).get_job(job["job_id"])
    assert restored["status"] == "partial"
    assert restored["result"]["inserted_blocks"] == 1
    assert "raw" not in restored["result"]


def test_inflight_job_becomes_interrupted_after_restart(tmp_path):
    from src.pictova.app.state import JobRegistry

    reg = JobRegistry(directory=tmp_path)
    job_id = "11111111-2222-4333-8444-555555555555"
    reg._persist({
        "job_id": job_id, "kind": "studio_attach",
        "status": "running", "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"site": "yoldaolmak", "post_id": 71},
        "result": None, "error": None,
    })
    restored = JobRegistry(directory=tmp_path).get_job(job_id)
    assert restored["status"] == "interrupted"
    assert "inspect WordPress" in restored["error"]


def test_persist_failure_never_starts_paid_job(monkeypatch, tmp_path):
    from src.pictova.app.state import JobRegistry

    reg = JobRegistry(directory=tmp_path)
    monkeypatch.setattr(reg, "_persist", MagicMock(side_effect=OSError("read-only disk")))
    runner = MagicMock()
    with pytest.raises(OSError):
        reg.create_job(kind="studio_attach", payload={"post_id": 71}, runner=runner)
    assert not reg.list_jobs()
    runner.assert_not_called()


def _scan_db(tmp_path):
    db = tmp_path / "assets.db"
    con = sqlite3.connect(db)
    con.execute("""
    CREATE TABLE asset_index(
        source_id TEXT PRIMARY KEY, vision_scan_status TEXT,
        vision_last_scanned_at TEXT, vision_last_error TEXT,
        ai_keywords_json TEXT, scene TEXT, activity TEXT, summary TEXT,
        people_json TEXT, story_score REAL
    )
    """)
    con.execute("INSERT INTO asset_index(source_id,vision_scan_status) VALUES ('a','pending')")
    con.commit()
    con.close()
    return str(db)


def test_scan_lease_prevents_duplicate_paid_analysis_and_recovers_errors(tmp_path):
    from scripts.fast_scan import _claim_source, _update_done, _update_error

    db = _scan_db(tmp_path)
    lease = _claim_source(db, "a")
    assert lease
    assert _claim_source(db, "a") is None

    # Old worker must not overwrite newer lease state.
    assert _update_done(db, "a", {"keywords": []}, lease="stale") is False
    assert _update_error(db, "a", "provider_failure", lease=lease) is True
    assert _claim_source(db, "a") is None

    retry = _claim_source(db, "a", retry_errors=True)
    assert retry and retry != lease
    assert _update_done(db, "a", {"keywords": ["castle"]}, lease=lease) is False
    assert _update_done(db, "a", {"keywords": ["castle"]}, lease=retry) is True
    assert _claim_source(db, "a", retry_errors=True) is None

    con = sqlite3.connect(db)
    assert con.execute("SELECT vision_scan_status,vision_last_error FROM asset_index").fetchone() == (
        "done", None,
    )
    con.close()


def test_scan_reclaims_only_stale_in_progress_leases(tmp_path):
    from scripts.fast_scan import _claim_source

    db = _scan_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("""
        UPDATE asset_index SET vision_scan_status='scanning',
        vision_last_scanned_at='2025-01-01T00:00:00+00:00'
        WHERE source_id='a'
    """)
    con.commit()
    con.close()
    assert _claim_source(db, "a") is not None


def test_processing_errors_are_reported_to_caller(monkeypatch, tmp_path):
    from src.pictova.engine import processor

    class FakeProcessor:
        def __init__(self, work_dir):
            self.work_dir = tmp_path

        def process_image(self, **kwargs):
            if kwargs["input_path"].endswith("bad.jpg"):
                raise PermissionError("asset unavailable")
            return {"is_panoramic": False, "input": kwargs["input_path"]}

    monkeypatch.setattr(processor, "YOImageProcessor", FakeProcessor)
    result = processor.process_selected_images(["/fake/bad.jpg", "/fake/good.jpg"])
    assert len(result["processed_images"]) == 1
    assert result["failed_images"] == [{"file": "bad.jpg", "reason": "permission_denied"}]
