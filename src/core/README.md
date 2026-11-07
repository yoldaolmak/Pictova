# Legacy compatibility modules

`src/core/` remains for compatibility with the native Pictova engine and older callers.

Current modules: `database.py`, `filter.py`, `media_publish.py`, `media_quality.py`, `metadata_generator.py` and `processor.py`.

New product behavior belongs in `src/pictova/engine/`. Do not add an alternate publishing pipeline here. The legacy orchestrator remains at `src/main.py` and lacks the native path's complete safeguards.

See [Native vs. legacy](../../docs/architecture/native-vs-legacy.md).
