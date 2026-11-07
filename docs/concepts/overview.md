# Overview

Pictova selects existing images for WordPress H2/H3 sections, processes them, generates editorial metadata and places approved media in Gutenberg.

```text
review → plan → process → attach
```

`review` reads the post. `plan` finds candidates without licensing or publishing. `process` prepares files and may download licensed media. `attach` writes to WordPress. Explicit `guard` modes can also modify managed media.

Selection is section-specific: a broad destination or generic image does not satisfy a named place, product or landmark. Missing matches remain empty. Candidate metadata and model-generated queries are not visual proof.

Pictova does not create images and has no dependency on another editorial product. Its native CLI and optional local Studio share one publishing engine.

See [Selection](semantic-selection.md), [Studio](../guides/studio.md) and [Architecture](../architecture/overview.md).
