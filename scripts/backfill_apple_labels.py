#!/usr/bin/env python3
"""Backfill missing Apple Photos labels in the local Visual Memory index.

This script only changes ``visual_memory.db``. It never writes to Photos or
WordPress. It must run on the Mac that owns the Photos library.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.config import get_visual_memory_db_path


def _photos_db() -> Any:
    if sys.version_info < (3, 10):
        raise RuntimeError("Apple label backfill Python 3.10+ gerektirir")
    try:
        import osxphotos
    except ImportError as exc:
        raise RuntimeError("Apple label backfill için `pip install '.[macos]'` çalıştırın") from exc
    return osxphotos.PhotosDB()


def _source_ids(con: sqlite3.Connection, *, force: bool, limit: int) -> list[str]:
    where = "" if force else "WHERE COALESCE(apple_labels_json, '[]') IN ('', '[]')"
    query = f"SELECT source_id FROM asset_index {where} ORDER BY source_id"
    params: list[int] = []
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    return [str(row[0]) for row in con.execute(query, params)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Etiketi olan kayıtları da yeniden oku")
    parser.add_argument("--limit", type=int, default=0, help="İşlenecek en fazla kayıt; 0=sınırsız")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if args.limit < 0 or args.batch_size < 1:
        parser.error("--limit negatif olamaz ve --batch-size en az 1 olmalı")

    db_path = get_visual_memory_db_path()
    if not db_path.exists():
        print(f"✗ Visual Memory DB bulunamadı: {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    try:
        source_ids = _source_ids(con, force=args.force, limit=args.limit)
    except sqlite3.Error as exc:
        con.close()
        print(f"✗ asset_index okunamadı: {exc}", file=sys.stderr)
        return 1

    print(f"📸 {len(source_ids):,} kayıt için Apple label backfill başlıyor...")
    try:
        photos = _photos_db()
    except RuntimeError as exc:
        con.close()
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    updated = missing = errors = 0
    batch: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal updated, batch
        if not batch:
            return
        con.executemany(
            "UPDATE asset_index SET apple_labels_json = ? WHERE source_id = ?",
            batch,
        )
        con.commit()
        updated += len(batch)
        batch = []

    try:
        for source_id in source_ids:
            try:
                photo = photos.get_photo(source_id)
                if photo is None:
                    missing += 1
                    continue
                labels = [str(label) for label in (getattr(photo, "labels", None) or [])]
                batch.append((json.dumps(labels, ensure_ascii=False), source_id))
                if len(batch) >= args.batch_size:
                    flush()
                    print(f"  … {updated:,}/{len(source_ids):,} güncellendi")
            except Exception as exc:
                errors += 1
                print(f"  ✗ {source_id}: {type(exc).__name__}", file=sys.stderr)
        flush()
    finally:
        con.close()

    print(f"✅ Tamamlandı: {updated:,} güncellendi, {missing:,} bulunamadı, {errors:,} hata")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
