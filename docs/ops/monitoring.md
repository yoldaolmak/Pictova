# Monitoring and Diagnostics

Pictova is an operator-run application, not a managed production monitoring
service. Its structured command results, local index and bounded HTTP jobs
are the observable surfaces.

## Check local health

```bash
pictova health
```

The health result reports Python/module availability, the local photo index,
configured vision sources and WordPress site readiness. It does not guarantee
that a particular heading has a matching image.

## Inspect source selection

```bash
pictova review --site yoldaolmak --post 265713
pictova plan --site yoldaolmak --post 265713 --source auto --count 4
```

An empty exact-match list is a normal outcome when the subject cannot be
established. Check `heading_assignments` and `warnings`; do not compensate
for a missing named place with a generic image.

The local index can be queried without writing to WordPress:

```bash
python3 - <<'PY'
from src.pictova.engine.search import search_semantic_assets
print(search_semantic_assets(location_query="Istanbul", count=3))
PY
```

Empty results can mean no index, no relevant indexed photos, or an unavailable
path. There is no guarantee that every city must return a fixed count.

## Verify code changes

```bash
python3.10 -m pytest -q
```

The test suite uses offline fixtures and mocked providers. Passing tests
demonstrate code behavior under those inputs, not live publishing accuracy.

## Optional HTTP health and jobs

Start the server with a private token, following the
[HTTP API Reference](../reference/http-api.md).

```bash
curl -sS -H "Authorization: Bearer $PICTOVA_HTTP_TOKEN" \
  http://127.0.0.1:8040/health

curl -sS -H "Authorization: Bearer $PICTOVA_HTTP_TOKEN" \
  http://127.0.0.1:8040/jobs
```

Job state is process-local and not a durable queue or service-level agreement.
Do not expose the port or token to another network.

## Logs and privacy

CLI JSON may include private source paths and media details. Keep receipts in
a restricted local directory, avoid copying credentials into command lines,
and do not upload raw post content or Photos metadata to public issues.
