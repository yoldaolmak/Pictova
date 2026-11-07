# Local HTTP API

```bash
export PICTOVA_HTTP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
pictova serve --host 127.0.0.1 --port 8040
```

The service binds to loopback only. JSON endpoints require `Authorization: Bearer <token>`; the static Studio HTML/CSS/JS shell is public but contains no user data. Never expose the port to a network.

Requests must use `Content-Type: application/json`, at most 1 MiB. Existing non-Studio write endpoints reject browser `Origin` headers. Studio POST endpoints require the local same origin and a valid token. Host headers are checked against the bound listener.

| Route | Action |
| --- | --- |
| `GET /health`, `GET /stats` | Check readiness and local index |
| `POST /review`, `POST /plan` | Inspect article and candidate plan; no WordPress write |
| `POST /process` | Prepare images; may download/licence assets, no WordPress write |
| `POST /attach` | Publish via the native pipeline |
| `POST /guard` | Inspect; explicitly requested mutation modes can write |
| `POST /search`, `POST /gallery` | Image searches |
| `POST /jobs/attach` | Queue a publish job in process memory |
| `GET /jobs`, `GET /jobs/{id}` | Inspect job state |
| `GET /studio` | Static browser shell |
| `POST /studio/plan` | Create an expiring reviewed plan from a configured WordPress URL |
| `GET /studio/preview?plan=…&candidate=…` | Authenticated local preview |
| `POST /studio/apply` | Apply only accepted candidate IDs; licensed assets require separate consent |

Example:

```bash
curl -sS http://127.0.0.1:8040/plan \
  -H "Authorization: Bearer $PICTOVA_HTTP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"site":"yoldaolmak","post_id":265713,"count":4,"source":"auto"}'
```

Studio uses the same local HTTP server. Start it with `pictova studio` to open a browser with a temporary token, or open `/studio` and enter the existing token.

Jobs are not durable across server restarts. Consult the operation receipt and WordPress before retrying an uncertain write.
