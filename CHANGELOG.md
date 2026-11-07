# Changelog

## [Unreleased]

### Fixed
- Limit DepositPhotos licensed image transfers and resumed/cached files to 64 MiB, and reject unsafe asset IDs before constructing paths or licensing requests.
- Reject managed-media repair or reset when its Gutenberg gallery contains untracked images or editorial gallery captions; prevent media ID prefix collisions (e.g. 12 vs 123).
- Require section-specific image anchors rather than accepting the article's broad destination for a different H2/H3.
- Preserve the original named heading constraint when an optional model broadens an unsuccessful search.
- Reject automatic heading placement for an explicit query when no relevant heading matches.
- Normalize Turkish geographic spelling/plural variants and a bounded set of common bilingual editorial terms without assigning unsupported place aliases.
- Align the operator, installation, architectural and semantic selection documentation with the current native and legacy boundaries.
- Consolidated Photos indexing and Vision scanning under bounded `scripts/` entry points.
- Removed unsupported direct WordPress and DepositPhotos operations outside the native Pictova pipeline.
- Added strict local-runtime ignores for Photos indexes, provider caches, manifests, and agent artifacts.

### Changed
- Renamed package from `vil` → `pictova` across all modules, CLI, and pyproject.toml
- Removed AI agent coordination files (`AI_COORDINATION.md`, `QWEN_STATUS.md`)
- Full documentation restructure: concepts / guides / reference / architecture / ops

### Added
- Brand doctrine document: `docs/architecture/naming.md`
- CLI reference: `docs/reference/cli.md`
- HTTP API reference: `docs/reference/http-api.md`
- Configuration reference: `docs/reference/configuration.md`
- Site profiles reference: `docs/reference/profiles.md`
- Concept docs: overview, visual memory, semantic selection, pipeline, sources
- Guides: quickstart, installation, Mac Photos setup, WordPress setup, adding sources
- Architecture docs: system overview, native vs legacy, engine modules
- Ops docs: runbook, indexing, monitoring

## [0.1.0] — 2026-06

### Added
- `src/pictova/` canonical package root (formerly `src/vil/`)
- CLI: `pictova attach`, `pictova plan`, `pictova process`, `pictova review`, `pictova health`, `pictova serve`
- HTTP API: `/health`, `/review`, `/plan`, `/process`, `/attach`, `/jobs/attach`, `/jobs`, `/jobs/{id}`
- Async job registry (`src/pictova/app/state.py`)
- Native engine path (`src/pictova/engine/`): selector, processor, quality, metadata, publisher, gallery
- Vision-backed metadata with fallback to deterministic mode
- Mac Photos semantic index integration via `YO_VISUAL_MEMORY_DB`
- Apple Photos ML enrichment (location, scene, faces, blur/exposure)
- Structured attach output contract with `selected_assets`, `rejected_assets`, `uploaded_media_ids`, `inserted_blocks`, `duration_ms`
- `pyproject.toml` console script: `pictova`
- 19 passing tests
