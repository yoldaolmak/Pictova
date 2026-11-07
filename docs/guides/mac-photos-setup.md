# Mac Photos

Mac Photos is optional. Index the library on the Mac where the originals are accessible.

```bash
pip install -e '.[macos]'
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

Set `YO_VISUAL_MEMORY_DB` to the absolute index path when using a nondefault location. By default Pictova reads `data/visual_memory.db`.

Test the index without uploading:

```python
from src.pictova.engine.search import search_semantic_assets

print(search_semantic_assets(location_query="Sinop", count=5))
```

Optional enrichment:

```bash
python3 scripts/fast_scan.py --workers 1 --limit 50
```

The index may contain location, labels and people metadata. Routine selection excludes assets marked personal or video; review index access and filtering before use. Optimized iCloud photos need a local original before processing. Indexing does not modify the Photos originals.

See [Index operations](../ops/indexing.md) for verification and backup.
