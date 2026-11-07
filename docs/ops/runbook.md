# Pictova Operator Runbook

Use `review → plan → process → attach` for an individual WordPress post.
Only `attach` publishes. `guard` mutation modes need a separate deliberate
operator decision.

## Diagnose a post

```bash
pictova health
pictova review --site yoldaolmak --post 265713
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
```

Verify the selected site, the actual H2/H3 subjects and every candidate's
heading assignment. Read warnings: no exact candidate is a valid outcome.

## Prepare before WordPress writes

```bash
pictova process --site yoldaolmak --post 265713 --count 4 --source auto
```

This can download and transform local files, but must not upload them to the
post. Inspect quality and metadata results.

## Publish

```bash
pictova attach --site yoldaolmak --post 265713 --count 4 --source auto --engine native
```

A short selection is not permission to insert generic assets. Keep existing
unmanaged image blocks intact. To inspect managed media without modifying a
post:

```bash
pictova guard --site yoldaolmak --post 265713
```

`guard --repair`, `--reposition`, `--adopt`, and `--reset` are separate
write operations; verify ownership and back up the post before using them. If a Pictova image
shares a Gutenberg gallery with an editor-owned image or an untracked caption,
reset/reposition refuses the operation rather than removing the shared block.

## Verify the local installation

```bash
python3.10 -m pytest -q
```

Automated tests use isolated fixtures and mocked providers; a successful
test run does not prove live WordPress publication or visual accuracy.

## Optional local HTTP server

```bash
export PICTOVA_HTTP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
pictova serve --host 127.0.0.1 --port 8040
```

Every HTTP route requires a Bearer token:

```bash
curl -sS -H "Authorization: Bearer $PICTOVA_HTTP_TOKEN" \
  http://127.0.0.1:8040/health
```

The service is not suitable for public exposure; see the
[HTTP API Reference](../reference/http-api.md).

## Index local Photos

```bash
python3 scripts/index_turkey_photos.py
python3 scripts/rebuild_fts.py
python3 scripts/build_destination_index.py
```

These commands update local index state, not WordPress. Follow the
[Indexing Guide](indexing.md) before running them on a real Photos library.

## Diagnose a missing image

- No candidate for a specific heading: inspect the heading name and source
  title; the correct action may be to leave it empty.
- A provider error: verify configuration and connectivity; do not rerun a
  licensed download blindly or weaken matching.
- Local images rejected during `process`: inspect the quality report and
  original file, without bypassing rejection.
- WordPress access denied: verify the selected site profile and its
  application password in the local environment, never in logs.

Optional `fast_scan.py` vision enrichment is subject to
`PICTOVA_VISION_DAILY_LIMIT`; review its budget before a real scan.
