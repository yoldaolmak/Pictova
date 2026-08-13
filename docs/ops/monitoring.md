# Monitoring

## Health Check

```bash
pictova health
```

```bash
# Via HTTP
curl -s http://127.0.0.1:8040/health
```

The result reports configuration, WordPress readiness, provider availability
and local-index status. It does not publish or upload media.

If this fails: check that `pictova serve` is running and the port is correct.

## Visual Memory Status

```bash
python3 - <<'PY'
from src.main import search_semantic_assets
r = search_semantic_assets('Istanbul', count=3)
print(f"Status: {'ok' if r else 'no results — check YO_VISUAL_MEMORY_DB'}")
PY
```

## Test Suite

```bash
python3.10 -m pytest -q
```

Run after any code change. All tests should pass. A failing test in CI means something in the engine contract changed.

## Job Queue Health (HTTP mode)

```bash
curl -s http://127.0.0.1:8040/jobs | python3 -m json.tool
```

Check for jobs stuck in `running` state for more than 5 minutes — this indicates a processing hang.

## What to Watch

| Signal | Normal | Investigate if |
|--------|--------|----------------|
| `attach` result | `success` or intentional `no_candidates` | raw exception or partial upload |
| Quality gate rejection rate | reported in receipt | unexpected generic fallback |
| Visual memory query results | ≥ 3 for any Turkish city | 0 for major cities |
| Test suite | All passed | Any failure |

## Logs

Pictova returns structured JSON on stdout. Capture a receipt with:

```bash
pictova attach --site yoldaolmak --post 265713 2>&1 | tee /tmp/pictova-run.log
```
