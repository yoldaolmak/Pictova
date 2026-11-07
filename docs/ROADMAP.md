# Roadmap

Pictova is an independent image-selection and WordPress placement tool. This file tracks remaining product work, not a promise of enterprise readiness.

## Available

- CLI: `review`, `plan`, `process`, `attach`, `guard`, `health`.
- Local Studio: WordPress URL → heading-aware candidate previews → reject/approve → native attach.
- Local Visual Memory, configured image sources and bounded vision metadata.
- Per-post attach lock, managed-media safeguards, and offline CI.

## Open priorities

1. **Visual accuracy:** Evaluate real labeled images across Turkish/international place names, look-alike landmarks and negative cases. Current metadata matching and synthetic tests are not visual ground truth.
2. **Live WordPress verification:** Exercise review → approved selection → safe insertion → verification → rollback on a controlled test post, including failures and concurrent edits.
3. **Source trust:** Audit signed CDN download URLs and redirects; document provider permissions and license-consumption behavior.
4. **Maintainability:** Gradually reduce legacy dependencies and large selector/WordPress modules without changing CLI contracts or introducing parallel engines.

## Limits

Studio remains loopback-only. iCloud-only assets without safe previews cannot be approved through Studio. Background jobs are in memory, not a durable distributed queue.

See [Architecture](architecture/overview.md), [Security](../SECURITY.md) and [Studio](guides/studio.md).
