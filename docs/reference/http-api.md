# HTTP API Reference

Start the authenticated local server:

```bash
export PICTOVA_HTTP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
pictova serve --host 127.0.0.1 --port 8040
```

The server refuses to start without a token of at least 32 ASCII characters.
It binds **only to loopback** (127.0.0.1 or localhost); it does not provide TLS
and must not be exposed to the LAN or public Internet. Every endpoint, including
health checks, requires `Authorization: Bearer <token>`. Keep the token out of
logs, repositories, and shared command transcripts.

POST requests require `Content-Type: application/json`, a body of at most
1 MiB, and no `Origin` header (browser clients are intentionally unsupported).
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
  -H "Authorization: Bearer $PICTOVA_HTTP_TOKEN" \
  -d '{"site":"yoldaolmak","post_id":265713,"count":4,"source":"auto"}'
```

An HTTP 400 contains a structured failed result. Provider or exact-match
failures are represented as no selected files plus diagnostics, not as a
generic fallback.
