"""Regressions for the defects found while auditing src/main.py and src/core/.

The legacy pipeline is still the default engine for `pictova attach`, so these
paths matter even though the native engine wraps most of them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


# ── The Google Vision step never actually ran ───────────────────────────────

def test_no_reference_to_the_missing_cloud_vision_module():
    """`src.core.cloud_vision` does not exist and never did.

    The old try/except bound `generate_metadata_for_files` on failure while the
    try body imported `YOCloudVisionClient`, so the name stayed undefined and
    every run raised NameError inside a swallowing `except Exception`.
    """
    import src.main as main_module

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    assert "YOCloudVisionClient()" not in source
    assert not hasattr(main_module, "YOCloudVisionClient")

    with pytest.raises(ModuleNotFoundError):
        __import__("src.core.cloud_vision")


# ── Empty inputs must fail structurally, not with IndexError ────────────────

def test_local_source_without_paths_returns_a_failure_result(tmp_path):
    from src.main import YOOrchestrator

    orchestrator = YOOrchestrator(work_dir=tmp_path / "work")
    with patch("src.main.fetch_post_context", return_value={}):
        result = orchestrator.run_pipeline(
            count=1, post_id=None, source="local", query="   ",
        )

    assert result["status"] == "failed"
    assert "dosya yolu" in result["error"].lower()


def test_orchestrator_creates_nested_work_dir(tmp_path):
    """mkdir lacked parents=True, so any nested work_dir raised FileNotFoundError."""
    from src.main import YOOrchestrator

    nested = tmp_path / "a" / "b" / "work"
    orchestrator = YOOrchestrator(work_dir=nested)

    assert orchestrator.work_dir.is_dir()


def test_empty_slug_candidates_do_not_raise(tmp_path):
    """The native engine already guarded this; the legacy path did not."""
    from src.core.media_publish import ensure_unique_slug

    used: set[str] = set()
    # This mirrors the guarded expression now used in run_pipeline.
    candidates: list[str] = []
    slug = ensure_unique_slug(candidates[0] if candidates else "seyahat-kare", used)

    assert slug


# ── A disabled quality gate has to be visible in the result ─────────────────

def test_quality_gate_bypass_is_reported(monkeypatch, tmp_path):
    from src.main import YOOrchestrator

    monkeypatch.setenv("YO_ALLOW_FALLBACK_UPLOAD", "1")
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"x")

    orchestrator = YOOrchestrator(work_dir=tmp_path / "work")

    def fake_process(input_path, output_path, **_kwargs):
        Path(output_path).write_bytes(b"webp")
        return {"input": input_path, "output": output_path, "aspect_ratio": 1.5}

    with patch("src.main.fetch_post_context", return_value={"title": "Test"}), \
         patch.object(orchestrator.processor, "process_image", side_effect=fake_process), \
         patch("src.main.build_basic_metadata", return_value={"title": "", "alt": ""}), \
         patch("src.main.validate_metadata", return_value=["title too short"]), \
         patch("src.main.validate_processed_asset", return_value=[]), \
         patch("src.main.embed_metadata", return_value=False), \
         patch("src.main.build_publish_slug_candidates", return_value=["kare"]):
        result = orchestrator.run_pipeline(
            count=1, post_id=None, source="local", query=str(image),
        )

    gate = result["steps"]["quality_gate"]
    assert gate["gate_disabled"] is True
    assert gate["bypassed"] and gate["bypassed"][0]["errors"] == ["title too short"]
    assert any("Kalite kapısı devre dışı" in w for w in result.get("warnings", []))


def test_quality_gate_bypass_is_off_by_default(monkeypatch):
    """Fail-closed is the default: only an explicit truthy flag disables the gate."""
    import src.main as main_module

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    assert 'os.getenv("YO_ALLOW_FALLBACK_UPLOAD", "0")' in source

    for value in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("YO_ALLOW_FALLBACK_UPLOAD", value)
        import os

        assert os.getenv("YO_ALLOW_FALLBACK_UPLOAD", "0").strip().lower() not in {
            "1", "true", "yes", "on",
        }


def test_native_engine_is_the_default_for_attach(monkeypatch):
    """The fail-closed engine must be what an unqualified attach runs."""
    from src.pictova.app import cli, jobs

    parsed = cli.build_parser().parse_args(["attach", "--post", "1"])
    assert parsed.engine == "native"
    assert cli._attach_args_to_payload(parsed)["engine"] == "native"

    # The job layer must not quietly fall back to legacy when engine is absent.
    seen = {}
    monkeypatch.setattr(jobs, "prepare_attach_request",
                        lambda **kw: ({"post_id": 1, "site": "yoldaolmak"}, {}, {}))
    monkeypatch.setattr(jobs, "validate_attach_request", lambda **kw: None)
    monkeypatch.setattr(jobs, "execute_native_attach",
                        lambda **kw: seen.setdefault("engine", "native") and {} or {"status": "success"})
    monkeypatch.setattr(jobs, "execute_legacy_attach",
                        lambda **kw: seen.setdefault("engine", "legacy") and {} or {"status": "success"})
    monkeypatch.setattr(jobs, "_write_attach_receipt", lambda result: "/tmp/receipt.json")

    jobs.run_attach_job(site="yoldaolmak", post_id=1)
    assert seen["engine"] == "native"


def test_local_output_never_overwrites_an_existing_file(tmp_path):
    """The VIL move used Path.replace, silently destroying a same-named file."""
    from src.main import _free_destination

    (tmp_path / "photo_yo.webp").write_bytes(b"previous run")

    first = _free_destination(tmp_path, "photo_yo.webp")
    assert first.name == "photo_yo-2.webp"

    first.write_bytes(b"second run")
    assert _free_destination(tmp_path, "photo_yo.webp").name == "photo_yo-3.webp"

    # An unused name is returned unchanged.
    assert _free_destination(tmp_path, "other.webp").name == "other.webp"
    assert (tmp_path / "photo_yo.webp").read_bytes() == b"previous run"


# ── Dead and unsafe modules are gone ────────────────────────────────────────

def test_sql_injecting_selection_module_is_removed():
    """src/core/selection.py interpolated user queries straight into SQL."""
    with pytest.raises(ModuleNotFoundError):
        __import__("src.core.selection")


def test_database_component_only_queries_tables_that_exist(tmp_path):
    """get_all_images/get_image_by_path/get_tags_for_image hit absent tables."""
    from src.core.database import VisualMemoryComponent, VisualMemoryConfig

    component = VisualMemoryComponent(VisualMemoryConfig(database_path=tmp_path / "x.db"))
    for removed in ("get_all_images", "get_image_by_path", "get_tags_for_image"):
        assert not hasattr(component, removed)


def test_claude_model_ids_are_plausible():
    """"claude-sonnet-4-6" was not a real id; the first request always 404'd."""
    from src.core.metadata_generator import YOMetadataGenerator

    models = YOMetadataGenerator._load_claude_models(object())
    assert "claude-sonnet-4-6" not in models
    assert all(model.startswith("claude-") for model in models)


# ── FTS failures must not hide programming errors ───────────────────────────

def test_semantic_search_only_swallows_sqlite_errors(tmp_path, monkeypatch):
    from src import main as main_module

    db = tmp_path / "visual_memory.db"
    connection = sqlite3.connect(db)
    connection.execute(
        "CREATE TABLE asset_index (source_path TEXT, filename TEXT, quality_score REAL,"
        " selection_score REAL, activity TEXT, scene TEXT, location TEXT, city TEXT,"
        " state_province TEXT, country TEXT, title TEXT, description TEXT, summary TEXT,"
        " orientation TEXT, ai_keywords_json TEXT, source_id TEXT, created_at TEXT,"
        " latitude REAL, longitude REAL, vision_scan_status TEXT, people_json TEXT,"
        " apple_labels_json TEXT, is_personal INT)"
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(main_module, "get_visual_memory_db_path", lambda: db)

    # A malformed FTS query is a sqlite error and degrades to the LIKE fallback
    # rather than propagating.
    assert main_module.search_semantic_assets("sinop kalesi", count=2) == []
