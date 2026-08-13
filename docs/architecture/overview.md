# System Overview

## Layers

Pictova is structured in three layers. Each layer has a single responsibility and a clean boundary.

```
┌─────────────────────────────────────┐
│           App Surface               │
│   CLI · HTTP API · Python API       │
│   src/pictova/app/                  │
├─────────────────────────────────────┤
│           Engine                    │
│  selector · processor · publisher   │
│  metadata · quality · gallery       │
│   src/pictova/engine/               │
├─────────────────────────────────────┤
│        Providers & Profiles         │
│  WordPress · Unsplash · Deposit     │
│  Site-specific rules                │
│  src/pictova/providers/             │
│  src/pictova/profiles/              │
└─────────────────────────────────────┘
```

## App Surface (`src/pictova/app/`)

The entry points. Nothing here contains business logic.

| Module | Purpose |
|--------|---------|
| `cli.py` | `pictova` command — parses args, calls engine |
| `api.py` | Python-callable wrappers: `attach_images()`, `review_post()`, `plan_attach()` |
| `server.py` | HTTP server — routes requests to `api.py` |
| `jobs.py` | Async job orchestration — wraps `api.py` for background execution |
| `state.py` | In-memory job registry |
| `health.py` | Health check logic |

## Engine (`src/pictova/engine/`)

Business logic. No I/O here except through injected providers.

| Module | Responsibility |
|--------|---------------|
| `selector.py` | Query sources, enforce exact anchors, and build ranked candidates |
| `processor.py` | Download, resize, convert, watermark-strip |
| `quality.py` | Score-based gate: reject blurry, over/underexposed, wrong aspect |
| `metadata.py` | Generate evidence-based alt text and concise editorial metadata |
| `publisher.py` | Prepare validated media for WordPress publishing |
| `gallery.py` | Native gallery block construction |
| `attach.py` | Pipeline orchestration: ties all engine modules together |

## Providers (`src/pictova/providers/`)

External I/O adapters. One per source or destination.

| Module | Interface |
|--------|-----------|
| `wordpress.py` | Read post context and resolve the supported site |

Native providers include DepositPhotos and Wikimedia; free-source fallback is
subject to the same exact-match gate as local candidates.

## Profiles (`src/pictova/profiles/`)

Per-site rules. No logic — only configuration values consumed by the engine and providers.

| Module | Site |
|--------|------|
| `yoldaolmak.py` | yoldaolmak.com (active) |

## Data Flow

```
User input (post_id + options)
        │
        ▼
    cli.py / api.py / server.py
        │
        ▼
    attach.py  ←────── profiles/
        │
        ├──▶ selector.py  ←─── providers/* (Unsplash, Visual Memory)
        │
        ├──▶ processor.py
        │
        ├──▶ quality.py
        │
        ├──▶ metadata.py  ←─── vision AI (optional)
        │
        └──▶ publisher.py ─────▶ providers/wordpress.py ──▶ WordPress
```

## Legacy Core

`src/core/` and `src/main.py` contain the original orchestration code. The native engine (`src/pictova/engine/`) wraps or replaces these incrementally. Both paths produce the same structured output contract.

See [Native vs Legacy Engine](native-vs-legacy.md).
