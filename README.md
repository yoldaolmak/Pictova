# Pictova

Pictova selects, prepares, names, and places images in WordPress posts. It is
designed for editorial use: a named place, product, or numbered section must
have an evidence-backed candidate. When that contract cannot be met, selection
stops instead of filling the article with a generic image.

## What it does

- reads a WordPress post and its H2/H3 structure;
- matches local Photos, DepositPhotos, Wikimedia, or free-source candidates to
  the post and the target heading;
- creates short Turkish SEO metadata from visual evidence and article copy;
- publishes native Gutenberg image or gallery blocks through the supported
  WordPress adapter; and
- records enough state to verify or repair Pictova-managed media later.

`attach` is the only publishing path. `review`, `plan`, and `process` are safe
previews and never modify WordPress.

## Install

Pictova requires Python 3.10 or later.

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

On macOS, install the optional Photos indexer support too:

```bash
pip install -e '.[macos]'
```

Populate only the providers and WordPress sites you intend to use, then verify
the local configuration without publishing:

```bash
pictova health
```

## Use

```bash
# Read a post; no external write.
pictova review --site auto --post 265713

# See exact candidates and target headings; no download or publish.
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto

# Select and process without sending media to WordPress.
pictova process --site yoldaolmak --post 265713 --count 4 --engine native

# Full native pipeline: select, validate, upload, place, and verify.
pictova attach --site yoldaolmak --post 265713 --count 4 --engine native
```

Use `--source deposit` when a licensed DepositPhotos-only run is required. An
exact match that cannot be found or downloaded returns a structured incomplete
result; it does not fall back to a loosely related image.

## Mac Photos index

The Photos index is local runtime state, not repository content:

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py

# Optional, bounded visual enrichment.
python3 scripts/fast_scan.py --workers 1 --limit 50
```

See [Mac Photos setup](docs/guides/mac-photos-setup.md) for prerequisites and
[Indexing](docs/ops/indexing.md) for the safety limits.

## Project layout

```text
src/pictova/app/       CLI and HTTP surface
src/pictova/engine/    selection, placement, metadata, processing
src/pictova/providers/ supported source and WordPress adapters
src/services/          WordPress write verification and media guard
scripts/               bounded local indexing and read-only analysis tools
tests/                 regression and contract tests
```

## Documentation

- [Concepts](docs/README.md)
- [CLI reference](docs/reference/cli.md)
- [Configuration](docs/reference/configuration.md)
- [Native engine architecture](docs/architecture/overview.md)
- [Operational runbook](docs/ops/runbook.md)
- [Contributing](CONTRIBUTING.md)

## Verification

```bash
python3.10 -m pytest -q
```

The local `data/` caches, Photos index, provider cache, manifests, and agent
indexes are intentionally ignored by Git.
