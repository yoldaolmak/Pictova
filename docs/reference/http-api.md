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

POST requests require 'Content-Type: application/json' and a body of at most
1 MiB. Existing JSON write routes reject browser Origin headers. The dedicated
Studio routes accept only an identical local Origin and a valid Bearer token.
Every route checks the Host authority against the local bound listener port,
rejecting DNS-rebinding aliases.
All bodies are JSON. The API mirrors the CLI’s structured result contract.

| Method | Path | Write? | Purpose |
|---|---|---:|---|
| 'GET' | '/studio' | No | Public static shell only; no user or site data without token. |
| 'GET' | '/studio/app.js', '/studio/style.css' | No | Static local UI assets. |
| 'POST' | '/studio/plan' | No | Resolve configured post URL; hold expiring plan. |
| 'GET' | '/studio/preview?plan=...&candidate=...' | No | Token-protected local thumbnail. |
| 'POST' | '/studio/apply' | Queues a write | One-use, selected candidate IDs plus explicit paid consent. |
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

Studio may be opened with 'pictova studio' (which launches a browser and
provides its ephemeral token in the URL fragment). The fragment is removed
from the browser address bar immediately and is never sent as a query string.
In the existing 'serve' mode an operator may enter the configured Bearer token
into the static Studio login field. The browser does not receive raw private
local paths; only opaque candidate IDs.

An HTTP 400 contains a structured failed result. Provider or exact-match
failures are represented as no selected files plus diagnostics, not as a
generic fallback.
