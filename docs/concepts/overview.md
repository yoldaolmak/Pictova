# Pictova Overview

Pictova is an independent image-selection and WordPress placement application.
Its job is not to fill image slots at any cost; it is to find an image whose
available evidence supports the article and the specific H2/H3 where it belongs.

## What it does

- Reads a WordPress article's title, slug and section headings.
- Searches the configured local Photos index and supported external providers.
- Checks named heading anchors against candidate metadata, rejecting generic
  or unrelated matches rather than guessing.
- Processes selected images and produces editorial metadata.
- Publishes supported Gutenberg media blocks through the native WordPress path,
  retaining managed-media information for verification and guarded repair.

Pictova **does not generate images**. It does not require Meridyen, Atlas,
Pictovap, or another product to run.

## The operator workflow

```text
review → plan → process → attach
```

`review` reads a post. `plan` inspects candidates without licensing/downloading
them. `process` prepares assets without writing to WordPress. Only `attach`
uploads and places media. The managed-media `guard` has separate explicit
repair and reset operations.

The requested image count is an upper bound, not a target to fill with
generic pictures. A named place without a supported match remains empty.

## Limits

A local filename, provider tag, or generated search query alone is not proof of
a place's identity. Common Turkish/English terms and spelling variants can be
matched, but different proper names (for example, local-language exonyms) need
a grounded equivalent before Pictova can treat them as identical.

The native `auto` path is the supported heading-aware selection route. Explicit
`local`, `vil`, `unsplash`, and compatibility/legacy paths have different
evidence boundaries: choosing a source directly does not establish that an
asset depicts a particular section. Review the plan and source metadata before
using such paths for publication.

See [Semantic Selection](semantic-selection.md), [The Pipeline](pipeline.md),
and the [CLI Reference](../reference/cli.md).
