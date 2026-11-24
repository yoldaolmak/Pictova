# Architecture

Pictova prepares and places existing photographs in travel-editorial WordPress
Gutenberg articles. The supported write path is native attach; Studio adds
single-use human approval to that path.

```text
WordPress post → H2/H3 subject → candidate selection
  → image preparation → metadata → quality gate
  → guarded Gutenberg insertion → readback + receipt
```

| Code | Responsibility |
| --- | --- |
| `src/pictova/app/` | CLI, loopback HTTP, Studio, job-status receipts |
| `src/pictova/engine/` | Selection, processing, metadata, quality, attach |
| `src/pictova/providers/` | Configured sources and WordPress reads |
| `src/services/wordpress.py` | Upload, Gutenberg insertion, managed-media verification |
| `src/visual_memory/`, `scripts/` | Local photo index and scans |
| `src/core/`, `src/main.py` | Compatibility helpers and legacy CLI engine |

The selector performs I/O. Heading-aware routes preserve subject identity;
direct-source modes have separate limits. Planning neither licenses media nor
changes WordPress. Processing may incur a license charge. Attach writes and
verifies the resulting managed blocks.

Studio plans expire and are process-local. Compact job-status receipts
persist locally; unfinished jobs become interrupted after restart. No
automatic resumption of writes or paid work.

The legacy engine retains compatibility only. Shared publishing outcome
checks do not make its selection and safeguards equivalent to native.

CI exercises synthetic image/model evidence and actual HTTP against a
loopback WordPress REST emulator, including insertion, readback, conflict
refusal and rollback. It does not establish live-site results or photo identity.

[Selection](../concepts/semantic-selection.md) · [Operation lifecycles](lifecycles.md) ·
[Engine modules](engine-modules.md) · [Security](../../SECURITY.md)
