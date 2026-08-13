# Semantic Selection

Semantic selection answers a narrow question: can this image support this post
or this heading without inventing a relationship that the visual evidence does
not establish?

## Evidence before ranking

Pictova derives post context, H2/H3 headings, and specific anchors such as a
place or named app. It then searches source evidence: local index fields,
provider title/tags, and visual metadata when available.

For a concrete heading, one compatible exact candidate is better than several
loosely related candidates. If a required anchor cannot be established, the
selector returns fewer files and explains the failure. It never fills the gap
with the first generic image from the same broad category.

## Heading-aware placement

When a post contains eligible H2/H3 sections, candidates are selected per
heading. Existing images are respected, and numbered “places to visit” sections
are preferred when measured editorial placement data supports them. A gallery
is formed only where the placement policy deliberately groups images.

## Inspecting a decision

```bash
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
```

The JSON result includes selected files, heading assignments, provider
diagnostics, and warnings. It is the first step before an attach run.
