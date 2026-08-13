#!/usr/bin/env python3
"""Destinasyon bazında fotoğraf kapsam raporu."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.config import get_visual_memory_db_path


DB_PATH = get_visual_memory_db_path()


def main():
    con = sqlite3.connect(str(DB_PATH))
    rows = con.execute("""
        SELECT
            COALESCE(city, state_province, 'bilinmiyor') AS location,
            COUNT(*) AS total,
            SUM(CASE WHEN source_path != '' THEN 1 ELSE 0 END) AS local_count,
            SUM(CASE WHEN source_path  = '' THEN 1 ELSE 0 END) AS icloud_count,
            SUM(CASE WHEN vision_scan_status = 'done' THEN 1 ELSE 0 END) AS scanned
        FROM asset_index
        GROUP BY COALESCE(city, state_province, 'bilinmiyor')
        ORDER BY total DESC
        LIMIT 40
    """).fetchall()
    con.close()

    print(f"{'Lokasyon':<28} {'Toplam':>7} {'Lokal':>7} {'iCloud':>7} {'Tarandı':>8}")
    print("-" * 60)
    for loc, total, local, icloud, scanned in rows:
        bar = "█" * min(int(local / 5), 20)
        print(f"{loc:<28} {total:>7,} {local:>7,} {icloud:>7,} {scanned:>8,}  {bar}")


if __name__ == "__main__":
    main()
