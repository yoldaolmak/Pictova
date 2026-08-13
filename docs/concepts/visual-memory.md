# Visual Memory

Visual Memory is Pictova's local image index. It is a SQLite database that stores metadata about every image in your library — including Apple Photos ML enrichments — and powers the semantic selection engine.

## What It Contains

Each record in the `asset_index` table represents one image and stores:

| Field | Description |
|-------|-------------|
| `source_path` | Absolute path to the original file |
| `filename` | File name |
| `title` | Human-readable title (from Photos or inferred) |
| `description` | Generated or Photos-sourced description |
| `summary` | Short text summary |
| `location` | Place name where the photo was taken |
| `city` | City extracted from Photos moment metadata |
| `country` | Country |
| `activity` | Activity detected (hiking, dining, etc.) |
| `scene` | Scene type (landscape, street, interior, etc.) |
| `quality_score` | Source-quality signal used for ranking |
| `apple_labels_json` | Labels supplied by Apple Photos, when available |
| `people_json` | People metadata supplied by Apple Photos, when available |
| `is_personal` / `is_video` | Safety flags that make an asset ineligible for normal selection |

## Why It Exists

Mac Photos stores originals with UUID-based paths that change across devices and library migrations. A path-only approach breaks silently. Visual Memory solves this by indexing semantic fields alongside paths, so the selection engine can match on `city`, `scene`, or `activity` even when the path structure is opaque.

## The Two Runtimes

Visual Memory operates across two runtimes:

**Index runtime** (`scripts/` in this repository):
- Scans Photos or local archives
- Writes the local `visual_memory.db`
- Optionally enriches it with Apple Photos metadata

**Consumer runtime** (the Pictova engine):
- Reads `visual_memory.db` via `YO_VISUAL_MEMORY_DB`
- Uses it only for semantic selection
- Never modifies the Photos library itself

The index is local runtime state and is intentionally excluded from Git.

## Indexing

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

The first command adds Mac Photos assets and marks personal or video items as
non-selectable. The latter commands rebuild lookup indexes. Run these only from
an explicitly supervised terminal session; they touch the local index, not WordPress.

Run all three after importing new photos or on a daily schedule.

See: [Indexing Ops Guide](../ops/indexing.md)

## Verification

```python
from src.main import search_semantic_assets
print(search_semantic_assets('Sinop', count=5))
```

A working index returns real file paths to Photos originals matching the query. An empty result means the index is missing, the `YO_VISUAL_MEMORY_DB` env var is unset, or no assets match.
