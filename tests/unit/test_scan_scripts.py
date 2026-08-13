from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def test_fast_scan_fallback_scene_activity_is_deterministic():
    from scripts.fast_scan import _fallback_scene_activity

    assert _fallback_scene_activity(["Beach", "walking"]) == ("beach", "walking")
    assert _fallback_scene_activity([]) == ("general", "travel")


@pytest.mark.parametrize(
    ("requested", "daily_count", "daily_limit", "expected"),
    [
        (0, 100, 1350, 1250),
        (50, 100, 1350, 50),
        (5000, 100, 1350, 1250),
        (50, 1350, 1350, 0),
        (50, 100, 0, 50),
        (0, 100, 0, 0),
    ],
)
def test_fast_scan_effective_limit_respects_daily_budget(
    requested: int,
    daily_count: int,
    daily_limit: int,
    expected: int,
):
    from scripts.fast_scan import _effective_limit

    assert _effective_limit(requested, daily_count, daily_limit) == expected


def test_fast_scan_update_done_handles_missing_optional_fields(tmp_path: Path):
    from scripts.fast_scan import _update_done

    db = tmp_path / "visual_memory.db"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE asset_index (
            source_id TEXT PRIMARY KEY,
            ai_keywords_json TEXT,
            scene TEXT,
            activity TEXT,
            summary TEXT,
            people_json TEXT,
            story_score REAL,
            vision_scan_status TEXT,
            vision_last_scanned_at TEXT,
            vision_last_error TEXT
        )
        """
    )
    con.execute("INSERT INTO asset_index (source_id) VALUES ('photo-1')")
    con.commit()
    con.close()

    _update_done(str(db), "photo-1", {"keywords": ["beach"], "alt": "Kıyı"})

    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT ai_keywords_json, scene, activity, summary, people_json, story_score, "
        "vision_scan_status, vision_last_error FROM asset_index WHERE source_id = 'photo-1'"
    ).fetchone()
    con.close()

    assert json.loads(row[0]) == ["beach"]
    assert row[1:4] == ("beach", "travel", "Kıyı")
    assert json.loads(row[4]) == []
    assert row[5:] == (0.0, "done", None)


def test_country_index_migrations_only_ignore_duplicate_columns(tmp_path: Path):
    from scripts.index_country_photos import _apply_migrations

    db = tmp_path / "visual_memory.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE asset_index (source_id TEXT PRIMARY KEY)")
    _apply_migrations(con)
    _apply_migrations(con)
    columns = {row[1] for row in con.execute("PRAGMA table_info(asset_index)")}
    con.close()

    assert {"state_province", "sub_admin_area", "apple_labels_json"} <= columns


def test_turkey_index_migrations_propagate_unrelated_sql_errors():
    from scripts import index_turkey_photos

    con = sqlite3.connect(":memory:")
    original = index_turkey_photos.MIGRATE_COLUMNS
    index_turkey_photos.MIGRATE_COLUMNS = ("ALTER TABLE missing ADD COLUMN nope TEXT",)
    try:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            index_turkey_photos._apply_migrations(con)
    finally:
        index_turkey_photos.MIGRATE_COLUMNS = original
        con.close()


def test_turkey_index_parser_accepts_a_bounded_scan():
    from scripts.index_turkey_photos import parse_args

    assert parse_args(["--limit", "25"]).limit == 25


def test_backfill_source_ids_respect_missing_label_filter(tmp_path: Path):
    from scripts.backfill_apple_labels import _source_ids

    con = sqlite3.connect(tmp_path / "visual_memory.db")
    con.execute("CREATE TABLE asset_index (source_id TEXT, apple_labels_json TEXT)")
    con.executemany(
        "INSERT INTO asset_index VALUES (?, ?)",
        [("empty", "[]"), ("missing", None), ("filled", json.dumps(["sea"]))],
    )

    assert _source_ids(con, force=False, limit=0) == ["empty", "missing"]
    assert _source_ids(con, force=True, limit=2) == ["empty", "filled"]
    con.close()
