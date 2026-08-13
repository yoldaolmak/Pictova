# Mac Photos Setup

Pictova can use your Mac Photos library as an image source. This guide covers indexing your library and connecting it to Pictova.

## How It Works

1. Pictova's local indexer scans your Photos originals
2. Apple Photos metadata (location, labels, people) is indexed when available
3. All metadata is written to a SQLite database (`visual_memory.db`)
4. Pictova reads this database via `YO_VISUAL_MEMORY_DB`

The indexer runs on the Mac that owns the Photos library. Pictova can consume
the resulting database elsewhere when `YO_VISUAL_MEMORY_DB` points to it.

## Step 1: Set Up the Index Runtime

Verify the project's Python environment:

```bash
./.venv/bin/python -V
# Python 3.10+
```

## Step 2: Index Your Photos Library

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

This step:
- Discovers Photos originals via `osxphotos`
- Keeps personal/family assets in the index but prevents their selection
- Writes source, location, people and Apple labels to `asset_index`

Expected output reports the number included, skipped, and any errors. Family,
personal, and video assets remain indexed but are not selectable for routine
content use.

## Step 3: Scan Visual Metadata (Optional)

```bash
python3 scripts/fast_scan.py --workers 1 --limit 50
```

This uses the configured local/remote Vision chain to enrich eligible images.
It skips personal and video assets. The default daily cap is 1,350 scans; pass
`--daily-limit 0` only for a supervised unlimited run.

This step may take several minutes for large libraries.

## Step 4: Connect to Pictova

In Pictova's `.env`:

```bash
YO_VISUAL_MEMORY_DB=/Users/yoldaolmak/Projects/Pictova/data/visual_memory.db
```

## Step 5: Verify

```bash
python3 - <<'PY'
from src.main import search_semantic_assets
results = search_semantic_assets('Sinop', count=5)
for r in results:
    print(r['source_path'])
PY
```

If you see real file paths to your Photos originals, the connection is working.

## Keeping the Index Fresh

After importing new photos, rerun the indexer and derived indexes:

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

For an unattended schedule, keep the same bounds and monitor its receipts. See
[Indexing Ops](../ops/indexing.md).

## Notes

- Photos originals must be downloaded to disk (not "Optimize Mac Storage")
- iCloud Photos in "optimized" mode may be indexed without a local original and
  cannot be used until the original is downloaded
- The indexer does not modify your Photos library in any way
