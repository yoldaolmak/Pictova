# Indexing

Visual Memory index maintenance guide.

## Index Location

```
/Users/yoldaolmak/Projects/Pictova/
  data/
    visual_memory.db     ← the index
  destination_index.json ← derived local lookup cache
  scripts/
    index_turkey_photos.py
    rebuild_fts.py
    build_destination_index.py
  .venv/
```

## What the Index Contains

The `asset_index` table. One row per image. Key fields:

- `source_path` — absolute path to original
- `location`, `city`, `country` — from Photos moment metadata
- `scene`, `activity` — from the optional Vision scan
- `quality_score` — source-quality signal used for ranking
- `apple_labels_json`, `people_json` — Photos-provided labels and people
- `is_personal`, `is_video` — never eligible for normal content selection

## Running the Indexer

### Full index (first time or after large import)

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

This is a local, potentially long-running operation. It does not publish or
alter WordPress content.

### Refresh after new photos

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

### Verify index health

```bash
python3 - <<'PY'
import sqlite3
db = "/Users/yoldaolmak/Projects/Pictova/data/visual_memory.db"
con = sqlite3.connect(db)
count = con.execute("SELECT COUNT(*) FROM asset_index").fetchone()[0]
with_location = con.execute("SELECT COUNT(*) FROM asset_index WHERE city IS NOT NULL").fetchone()[0]
print(f"Total assets: {count}")
print(f"With location: {with_location}")
PY
```

## Vision Scan Budget

Run scans explicitly, with a small bound on a tethered connection:

```bash
python3 scripts/fast_scan.py --workers 1 --limit 50
```

The default calendar-day cap is 1,350. Override it through
`PICTOVA_VISION_DAILY_LIMIT` or `--daily-limit`; zero means unlimited and is
intended only for an observed run.

## Rebuilding the Index

If the index is corrupt or you want a clean slate:

```bash
rm data/visual_memory.db
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```
