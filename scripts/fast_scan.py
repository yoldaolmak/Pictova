#!/usr/bin/env python3
"""Bounded parallel Vision scan for pending local Photos assets.

The scanner deliberately has a conservative daily default so a forgotten
terminal session cannot exhaust a free-tier quota or a tethered connection.
Use ``--daily-limit 0`` only for an explicitly supervised unlimited run.

Usage:
  python3 scripts/fast_scan.py --workers 2 --limit 120
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pictova.engine.vision_chain import analyze_image_vision_chain, has_any_vision_source
from src.utils.config import env_str, get_visual_memory_db_path


DB_PATH = get_visual_memory_db_path()
DEFAULT_DAILY_LIMIT = 1350
_SCENE_WORDS = (
    "coast", "beach", "mountain", "forest", "city", "urban", "rural",
    "sea", "lake", "river", "valley", "castle", "mosque", "church",
    "market", "bazaar", "harbor", "port", "ruins", "landscape", "nature",
)
_ACTIVITY_WORDS = (
    "walking", "hiking", "swimming", "sailing", "photography", "tourism",
    "travel", "dining", "shopping", "sightseeing",
)

_lock = threading.Lock()
_done = 0
_errors = 0
_total = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a short-lived worker connection that tolerates concurrent writers."""
    con = sqlite3.connect(db_path, timeout=30)
    con.execute("PRAGMA busy_timeout = 30000")
    return con


def _fallback_scene_activity(keywords: list[object]) -> tuple[str, str]:
    """Derive stable broad categories when a provider omits optional fields."""
    terms = {str(item).casefold() for item in keywords if isinstance(item, str)}
    scene = next((word for word in _SCENE_WORDS if word in terms), "general")
    activity = next((word for word in _ACTIVITY_WORDS if word in terms), "travel")
    return scene, activity


def _coerce_story_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score, 1.0))


def _default_daily_limit() -> int:
    configured = env_str("PICTOVA_VISION_DAILY_LIMIT")
    if configured is None:
        return DEFAULT_DAILY_LIMIT
    try:
        return max(0, int(configured))
    except ValueError:
        print(
            "[!] PICTOVA_VISION_DAILY_LIMIT geçersiz; varsayılan 1350 kullanılıyor.",
            file=sys.stderr,
        )
        return DEFAULT_DAILY_LIMIT


def _effective_limit(requested: int, daily_count: int, daily_limit: int) -> int:
    """Return the maximum rows this invocation may process; zero means unbounded."""
    if daily_limit == 0:
        return requested
    remaining = max(0, daily_limit - daily_count)
    if requested == 0:
        return remaining
    return min(requested, remaining)


def _update_done(con_path: str, source_id: str, result: dict[str, Any]) -> None:
    keywords = result.get("keywords") or []
    people = result.get("people") or []
    scene = str(result.get("scene") or "")
    activity = str(result.get("activity") or "")
    if not scene or not activity:
        fallback_scene, fallback_activity = _fallback_scene_activity(keywords)
        scene = scene or fallback_scene
        activity = activity or fallback_activity

    con = _connect(con_path)
    try:
        con.execute(
            """
            UPDATE asset_index SET
                ai_keywords_json = ?,
                scene = ?,
                activity = ?,
                summary = ?,
                people_json = ?,
                story_score = ?,
                vision_scan_status = 'done',
                vision_last_scanned_at = ?,
                vision_last_error = NULL
            WHERE source_id = ?
            """,
            [
                json.dumps(keywords, ensure_ascii=False),
                scene,
                activity,
                result.get("alt") or result.get("caption") or "",
                json.dumps(people, ensure_ascii=False),
                _coerce_story_score(result.get("story_score")),
                _now(),
                source_id,
            ],
        )
        con.commit()
    finally:
        con.close()


def _update_error(con_path: str, source_id: str, error: str) -> None:
    con = _connect(con_path)
    try:
        con.execute(
            """
            UPDATE asset_index SET
                vision_scan_status = 'error',
                vision_last_error = ?,
                vision_last_scanned_at = ?
            WHERE source_id = ?
            """,
            [error[:500], _now(), source_id],
        )
        con.commit()
    finally:
        con.close()


def _record_error(con_path: str, source_id: str, error: str) -> None:
    global _errors
    try:
        _update_error(con_path, source_id, error)
    except sqlite3.Error as db_error:
        error = f"{error}; error state yazılamadı: {db_error}"
    with _lock:
        _errors += 1
        print(f"  ✗ {source_id}: {error[:180]}", file=sys.stderr)


def _worker(rows: list[tuple[Any, ...]], db_path: str, worker_id: int) -> None:
    global _done
    for row in rows:
        source_id, source_path, city, state, country, raw_labels = row
        location = city or state or country or ""
        if not Path(source_path).exists():
            _record_error(db_path, source_id, "file_not_found")
            continue

        apple_labels: list[object] = []
        if raw_labels:
            try:
                loaded = json.loads(raw_labels)
                if isinstance(loaded, list):
                    apple_labels = loaded
            except (TypeError, ValueError):
                pass

        post_context = {
            "title": location,
            "slug": str(location).lower().replace(" ", "-"),
            "apple_labels": apple_labels,
        }
        try:
            result = analyze_image_vision_chain(
                source_path,
                location_hint=location,
                post_context=post_context,
            )
            _update_done(db_path, source_id, result)
        except Exception as exc:
            _record_error(db_path, source_id, f"{type(exc).__name__}: {exc}")
            continue

        with _lock:
            _done += 1
            percent = int(_done / _total * 100) if _total else 0
            print(
                f"  ✓ [{worker_id}] {Path(source_path).name} "
                f"({result.get('source', '?')}) {percent}% → {result.get('keywords', [])[:3]}"
            )


def main() -> None:
    global _done, _errors, _total
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0, help="Bu çalıştırmadaki en fazla kayıt; 0=limit yok")
    parser.add_argument(
        "--daily-limit",
        type=int,
        default=_default_daily_limit(),
        help="Takvim günündeki tamamlanmış scan üst sınırı; 0=sınırsız",
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers en az 1 olmalı")
    if args.limit < 0 or args.daily_limit < 0:
        parser.error("limitler negatif olamaz")

    if not has_any_vision_source():
        print("❌ Vision kaynağı yok.", file=sys.stderr)
        raise SystemExit(1)

    _done = _errors = _total = 0
    con = _connect(str(DB_PATH))
    try:
        daily_count = con.execute(
            """
            SELECT count(*) FROM asset_index
            WHERE vision_scan_status = 'done'
              AND date(vision_last_scanned_at) = date('now')
            """
        ).fetchone()[0]
        effective_limit = _effective_limit(args.limit, daily_count, args.daily_limit)
        if args.daily_limit and effective_limit == 0:
            print(
                f"🛑 Günlük vision bütçesi dolu ({daily_count}/{args.daily_limit}); tarama yapılmadı.",
                file=sys.stderr,
            )
            return

        query = """
            SELECT source_id, source_path, city, state_province, country, apple_labels_json
            FROM asset_index
            WHERE vision_scan_status = 'pending'
              AND source_path != '' AND source_path IS NOT NULL
            ORDER BY quality_score DESC
        """
        params: list[int] = []
        if effective_limit:
            query += " LIMIT ?"
            params.append(effective_limit)
        rows = con.execute(query, params).fetchall()
    finally:
        con.close()

    _total = len(rows)
    budget_text = "sınırsız" if args.daily_limit == 0 else f"{daily_count}/{args.daily_limit}"
    print(f"🔍 {_total} fotoğraf → {args.workers} paralel worker (günlük bütçe: {budget_text})")
    if not rows:
        return

    buckets: list[list[tuple[Any, ...]]] = [[] for _ in range(args.workers)]
    for index, row in enumerate(rows):
        buckets[index % args.workers].append(tuple(row))

    db_path = str(DB_PATH)
    threads = [
        threading.Thread(target=_worker, args=(buckets[index], db_path, index + 1))
        for index in range(args.workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    print(f"\n✅ Tamamlandı: {_done} başarılı, {_errors} hata")
    if _done == 0:
        return

    print("\n🔄 FTS indeksi yeniden oluşturuluyor...")
    from scripts import rebuild_fts

    rebuild_fts.main()
    print("\n🗺  Destination index güncelleniyor...")
    from scripts import build_destination_index

    build_destination_index.main()


if __name__ == "__main__":
    main()
