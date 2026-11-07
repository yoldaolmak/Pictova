# Review, Plan, Process, Attach

Pictova uses four ordered stages. A returned image is not necessarily safe to
publish: the selection gate and the eventual placement need to agree on its
specific heading.

| Stage | Reads / produces | Changes WordPress? |
| --- | --- | --- |
| `review` | WordPress article context and available headings | No |
| `plan` | Candidate selection, heading assignments and warnings | No |
| `process` | Locally prepared image files and validation outcomes | No |
| `attach` | Upload, Gutenberg insertion, media verification and result | **Yes** |

## Inspect before publishing

```bash
pictova review --site yoldaolmak --post 265713
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
pictova process --site yoldaolmak --post 265713 --count 4 --source auto --engine native
```

Use `plan` to inspect each candidate's target heading, source and warnings.
If the article names a particular location but no candidate supports that
name, an incomplete selection is the intended result. `process` may
download and transform images locally but does not upload them to WordPress.

## Publish deliberately

```bash
pictova attach --site yoldaolmak --post 265713 --count 4 --source auto --engine native
```

`attach` is the only normal publishing stage. It uses the native engine's
selection, quality, metadata and managed-media checks. The requested count is
a maximum; missing exact candidates must not be replaced with unrelated
images. Existing editorial image blocks are not general cleanup targets.

The CLI still accepts `--engine legacy` for compatibility. It invokes an
older orchestrator and does **not** carry the same native guarantees. Do not
use it as the default publishing route or extend its implementation.

## Local HTTP

An optional loopback-only HTTP service exposes the same workflow. It requires
a private Bearer token on **every** endpoint, including health and job reads.
See [HTTP API Reference](../reference/http-api.md) for authentication,
request limits and asynchronous attach jobs. The HTTP service is not a
public-network application.
