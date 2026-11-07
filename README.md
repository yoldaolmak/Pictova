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

## Pictova Studio — one-screen review

The CLI remains the primary automation surface. A local browser interface now
lets an editor paste a configured WordPress post URL, review actual image
previews and proposed section placements, reject candidates, and explicitly
approve only the remaining candidates for native publishing.

    pictova studio

Studio opens a loopback-only page with an ephemeral access token. It uses
short-lived, single-use approval plans rather than rediscovering images after
the user has approved them. Paid stock downloads require separate consent;
changes to the source photo or WordPress post stop the operation.

See the [Studio guide](docs/guides/studio.md) for current iCloud and provider
limits.

## Optional authenticated HTTP API

The CLI is the simplest operating surface. If local HTTP access is required,
set a private Bearer token before starting the server:

```bash
export PICTOVA_HTTP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
pictova serve --host 127.0.0.1 --port 8040
```

The HTTP server refuses non-loopback binding and rejects unauthenticated
requests. It is not a public network service. See the
[HTTP API reference](docs/reference/http-api.md) for request headers and limits.

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
- [Studio visual editor](docs/guides/studio.md)
- [Configuration](docs/reference/configuration.md)
- [Native engine architecture](docs/architecture/overview.md)
- [Operational runbook](docs/ops/runbook.md)
- [Contributing](CONTRIBUTING.md)
- [Security and trusted execution boundaries](SECURITY.md)

## Verification

```bash
python3.10 -m pytest -q
```

CI runs the same tests on Python 3.10–3.12 and enforces Flake8/Black.
Coverage is printed in the CI log; no external coverage upload is attempted.

The local `data/` caches, Photos index, provider cache, manifests, and agent
indexes are intentionally ignored by Git.
