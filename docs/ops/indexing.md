# Photo Index Operations

The optional local SQLite index stores source image paths, location, labels and visual metadata. It can include personal metadata. Keep it outside version control.

## Index and refresh

On the Mac with the Photos library and `osxphotos` installed:

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

Set `YO_VISUAL_MEMORY_DB` in `.env` if the index is not at `data/visual_memory.db`. These scripts update local index state; they do not write to WordPress.

## Inspect

```bash
pictova health
```

For a read-only row count:

```bash
python3 - <<'PY'
import sqlite3
from src.pictova.config import get_visual_memory_db_path

with sqlite3.connect(str(get_visual_memory_db_path())) as conn:
    print(conn.execute("SELECT COUNT(*) FROM asset_index").fetchone()[0])
PY
```

## Optional visual enrichment

```bash
python3 scripts/fast_scan.py --workers 1 --limit 50
```

`PICTOVA_VISION_DAILY_LIMIT` caps completed scans per day; `0` disables this guard. Confirm data and provider costs before changing the limit.

## Recover

Back up the index before rebuilding or migrating it. Verify the backup and the configured database path. Never delete the only copy to force a rebuild.

See [Mac Photos setup](../guides/mac-photos-setup.md).
