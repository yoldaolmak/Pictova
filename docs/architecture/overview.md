# Pictova Architecture

Pictova is a standalone Python application. The supported path keeps CLI/HTTP
parsing, editorial selection, media processing and WordPress writes at explicit
boundaries. It does not depend on another editorial or visual-operations product.

## Runtime structure

| Area | Location | Owns |
| --- | --- | --- |
| App | `src/pictova/app/` | CLI, local authenticated HTTP, request/result contracts |
| Engine | `src/pictova/engine/` | Heading selection, source orchestration, quality, metadata, placement, attach |
| Providers | `src/pictova/providers/` | External search, downloads and WordPress reads |
| WordPress adapter | `src/services/wordpress.py` | Media upload, Gutenberg changes, managed-media verification |
| Profiles | `src/pictova/profiles/` | Site configuration; no universal destination truth |
| Indexing | `scripts/` | Local Photos and Visual Memory maintenance |

The selector performs source reads/searches through providers and the local
index; the engine is **not** a pure in-memory layer. Avoid concealing paid
downloads or WordPress writes behind functions described as previews.

## Selection and publishing boundaries

```text
WordPress article + H2/H3 headings
  → section subjects and exact-match requirements
  → local index / configured image providers
  → candidate evidence checks and selection
  → image processing + metadata + quality validation
  → native attach (explicit write)
  → WordPress media and Gutenberg blocks
  → managed-media verification
```

A broad post location is not an acceptable substitute for a named heading.
A generic model-generated search query is not approval. If the original named
subject cannot be supported, that slot remains empty.

`review`, `plan`, and `process` do not alter WordPress content. `attach`
is the ordinary publishing path; mutating `guard` modes remain explicit.

## Legacy boundary

`src/main.py` and `src/core/` contain compatibility code. The CLI still
accepts `--engine legacy`, which calls the old orchestrator and lacks the
native path's complete checks. It is not the target for new product behavior.
See [Native and Legacy](native-vs-legacy.md).

## Verification limits

Offline tests cover selection, quality, HTTP and WordPress adapter contracts.
They do not independently prove whether an arbitrary photograph actually
depicts the section's place, and they do not constitute a live site deployment.
See [Semantic Selection](../concepts/semantic-selection.md) and
[Operations](../ops/runbook.md).
