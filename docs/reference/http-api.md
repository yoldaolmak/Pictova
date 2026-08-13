# HTTP API Reference

Start the local server:

```bash
pictova serve --host 127.0.0.1 --port 8040
```

All bodies are JSON. The API mirrors the CLI’s structured result contract.

| Method | Path | Write? | Purpose |
|---|---|---:|---|
| `GET` | `/health` | No | Configuration and readiness summary. |
| `GET` | `/stats` | No | Local visual-index summary. |
| `POST` | `/review` | No | Post context and candidate preview. |
| `POST` | `/plan` | No | Candidate plan. |
| `POST` | `/process` | No | Process without upload. |
| `POST` | `/attach` | Yes | Native attach pipeline. |
| `POST` | `/guard` | Mode-dependent | Managed-media inspection/repair. |
| `POST` | `/search` | No | Semantic image search. |
| `POST` | `/gallery` | No | Gallery/index query. |
| `POST` | `/jobs/attach` | Queues a write | Background attach job. |
| `GET` | `/jobs`, `/jobs/{id}` | No | Job state. |

Example dry run:

```bash
curl -sS -X POST http://127.0.0.1:8040/plan \
  -H 'Content-Type: application/json' \
  -d '{"site":"yoldaolmak","post_id":265713,"count":4,"source":"auto"}'
```

An HTTP 400 contains a structured failed result. Provider or exact-match
failures are represented as no selected files plus diagnostics, not as a
generic fallback.
