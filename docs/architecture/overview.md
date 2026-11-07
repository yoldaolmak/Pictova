# Architecture

Pictova has one supported publishing pipeline. CLI, local HTTP and Studio call the native engine; Studio adds operator review and one-use approval, not a second publisher.

```text
WordPress post + H2/H3
  → heading-aware candidates (local index / configured providers)
  → accepted assets → process → visual metadata → quality gate
  → WordPress Gutenberg insert → managed-media verification
```

| Code | Responsibility |
| --- | --- |
| `src/pictova/app/` | CLI, Studio, authenticated local HTTP and job results |
| `src/pictova/engine/` | Selection, processing, quality and native attach |
| `src/pictova/providers/` | Image-provider calls and WordPress reads |
| `src/services/wordpress.py` | Gutenberg upload, insertion, managed-media safeguards |
| `scripts/` | Local photo indexing and optional metadata scans |

The selector performs I/O; it is not a pure function. `plan` does not license images or write to WordPress. `process` can download or license; `attach` can upload and publish.

`src/core/` and `src/main.py` remain as legacy compatibility. `--engine legacy` does not provide all native safeguards; do not build new features there.

Offline tests verify contracts and rejection behavior, not whether a photograph truly depicts a particular place. Live WordPress publication is not validated by CI.

See [Selection](../concepts/semantic-selection.md), [Studio](../guides/studio.md) and [Security](../../SECURITY.md).
