# Diagnostics

Pictova is a local application, not a managed monitoring service. Jobs are process-local and may disappear when the HTTP server restarts.

```bash
pictova health
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
```

Check `status`, configured WordPress profiles, index readiness, `heading_assignments` and `warnings`. Empty matches do not mean a provider is broken.

For local HTTP:

```bash
curl -sS -H "Authorization: Bearer $PICTOVA_HTTP_TOKEN" http://127.0.0.1:8040/health
curl -sS -H "Authorization: Bearer $PICTOVA_HTTP_TOKEN" http://127.0.0.1:8040/jobs
```

Keep receipts private; they may contain local paths and article information. Verify WordPress state before retrying an uncertain publish. CI uses mocks, not live site checks.

See [Operations](runbook.md) and [Security](../../SECURITY.md).
