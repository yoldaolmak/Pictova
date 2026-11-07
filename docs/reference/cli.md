# CLI

```text
pictova <command> [options]
```

Commands return structured JSON to stdout.

| Command | WordPress write? | Function |
| --- | --- | --- |
| `health` | No (unless explicit `--verify-upload`) | Readiness; optional test upload and cleanup |
| `review` | No | Read post and headings |
| `plan` | No | Preview candidate selection |
| `process` | No | Prepare files; may download or license images |
| `attach` | Yes | Native publishing and verification |
| `guard` | Only explicit mutation modes | Managed-media inspection/repair/reset |
| `studio` | Only after approval | Open local single-screen editor |
| `serve` | Only through a write request | Start the authenticated local HTTP service |

## Common flags

```bash
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto --engine native
```

- `--site`: configured profile or `auto` (fails on ambiguous IDs).
- `--post`: WordPress post ID.
- `--count`: requested upper bound, not a minimum.
- `--source`: `auto`, `semantic`, `vil`, `local`, `unsplash`, `deposit`, `wikimedia`.
- `--engine`: `native` (default) or `legacy` (compatibility only).
- `--heading` / `--heading-level`: explicit placement target.

## Studio

```bash
pictova studio
```

For a manual browser session, configure `PICTOVA_HTTP_TOKEN` and use `pictova studio --no-open`. See [Studio](../guides/studio.md).

## Guard

```bash
pictova guard --site yoldaolmak --post 265713
```

`--repair`, `--reposition`, `--adopt` and `--reset` modify managed media. Operations refuse mixed-ownership galleries instead of deleting unrelated editorial images.
