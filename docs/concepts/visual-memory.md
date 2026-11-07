# Visual Memory

Visual Memory is the optional local SQLite index used for searching existing
photos. It stores metadata such as location, activity, scene, source path,
quality fields and Apple Photos labels when available. It does not change the
original Mac Photos library.

## Index and consumer

Indexing scripts build or update the `asset_index` table. The native selector
queries that table and may retrieve local or iCloud candidate references.
The database is local runtime state and is excluded from Git.

A local index result is **a candidate, not proof** that the photo depicts a
specific article section. The section-name gate uses the available indexed
metadata; unknown or generic evidence can cause rejection.

## Setup

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

These scripts modify the local index, not WordPress. Run them deliberately,
after reviewing [Mac Photos Setup](../guides/mac-photos-setup.md) and
[Indexing Operations](../ops/indexing.md).

Set `YO_VISUAL_MEMORY_DB` to the absolute path of the created index. Avoid
committing the database, source image paths or private Photos metadata.

## Test a local search

```python
from src.pictova.engine.search import search_semantic_assets

print(search_semantic_assets(location_query="Sinop", count=5))
```

An empty result may mean the index is missing, unconfigured, or lacks a
matching candidate. It is not an authorization to fall back to any image
from the same country.
