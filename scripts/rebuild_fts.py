#!/usr/bin/env python3
"""asset_search FTS5 indeksini asset_index'ten yeniden oluşturur.

document = city + state_province + country + location + keywords + ai_keywords + scene + activity
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.config import get_visual_memory_db_path


DB_PATH = get_visual_memory_db_path()


def _build_doc(row: sqlite3.Row) -> str:
    parts: list[str] = []
    for col in ("city", "state_province", "sub_admin_area", "country", "location",
                "scene", "activity", "summary", "title", "description"):
        v = row[col]
        if v:
            parts.append(str(v))

    for json_col in ("ai_keywords_json", "metadata_keywords_json", "apple_labels_json"):
        raw = row[json_col]
        if raw:
            try:
                kws = json.loads(raw)
                if isinstance(kws, list):
                    parts.extend(str(k) for k in kws if k)
            except Exception:
                pass

    return " ".join(parts)


def main():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    print("🗑  FTS temizleniyor...")
    con.execute("DROP TABLE IF EXISTS asset_search")
    con.execute("""
        CREATE VIRTUAL TABLE asset_search USING fts5(
            source_id UNINDEXED,
            document,
            tokenize = 'unicode61'
        )
    """)

    rows = con.execute("""
        SELECT source_id, city, state_province, sub_admin_area, country, location,
               scene, activity, summary, title, description,
               ai_keywords_json, metadata_keywords_json, apple_labels_json
        FROM asset_index
    """).fetchall()

    print(f"📄 {len(rows):,} kayıt FTS'e yazılıyor...")
    batch = []
    for row in rows:
        doc = _build_doc(row)
        if doc.strip():
            batch.append((row["source_id"], doc))

    con.executemany("INSERT INTO asset_search (source_id, document) VALUES (?, ?)", batch)
    con.commit()
    con.close()
    print(f"✅ FTS hazır — {len(batch):,} belge")


if __name__ == "__main__":
    main()
