# CLI Reference

```text
pictova <command> [options]
```

All commands return structured JSON on stdout. Progress and diagnostics go to
stderr so the result can be recorded or piped safely.

| Command | Writes WordPress? | Purpose |
|---|---:|---|
| `health` | No | Check local configuration and site readiness. |
| `review` | No | Read a post and return parsed context. |
| `plan` | No | Select candidates and heading assignments. |
| `process` | No | Select and prepare assets without uploading. |
| `attach` | Yes | Full native selection, publishing, and verification. |
| `guard` | Only with repair/reset modes | Inspect or repair Pictova-managed media. |
| `serve` | No until a request arrives | Start the local HTTP service. |

## Common attach options

```bash
pictova plan \
  --site yoldaolmak \
  --post 265713 \
  --count 4 \
  --source auto \
  --engine native
```

| Option | Values | Notes |
|---|---|---|
| `--site` | `auto`, configured site name | `auto` fails when a post exists on more than one site. |
| `--post` | integer | Required post ID. |
| `--count` | positive integer | Requested upper bound; exact-match policy may return fewer. |
| `--source` | `semantic`, `auto`, `vil`, `local`, `unsplash`, `deposit`, `wikimedia` | Use `deposit` for a licensed-only run. |
| `--engine` | `native`, `legacy` | Defaults to `native`; legacy is compatibility-only. |
| `--heading` / `--heading-level` | text / 2 or 3 | Explicitly constrain placement. |

## Guard

```bash
# Read-only integrity check
pictova guard --site yoldaolmak --post 265713

# Remove only Pictova-managed blocks, not unrelated editorial media
pictova guard --site yoldaolmak --post 265713 --reset
```

`--repair`, `--reposition`, `--adopt`, and `--reset` are write operations and
are intended for explicitly managed media only.
