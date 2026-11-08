# Tests

```bash
python3 -m pytest -q
python3 -m pytest tests/unit/test_studio.py -q
python3 -m pytest tests/unit/test_synthetic_model_contract.py -q
python3 -m pytest tests/integration/test_synthetic_wordpress_publish.py -q
```

`tests/unit/` covers image selection, rejection, metadata, WordPress media ownership, Studio security and providers. `tests/integration/` verifies CLI contracts and drives real Studio HTTP → native WebP pipeline → authenticated loopback WordPress REST emulation → Gutenberg readback and manifest. The synthetic tests also prove rollback, editor-conflict refusal, paid-consent enforcement and correct multi-heading placement. No production credentials are used.

External discovery and model responses remain deterministic fixtures; the WordPress REST emulator and Pictova HTTP/publishing methods are exercised over real loopback connections. No real website or paid provider is contacted. The synthetic OpenAI-compatible response tests verify transport and fail-closed behavior, **not** classification of actual image pixels.

Expected failures (`xfail`) document unresolved behavior; do not treat them as passing capabilities. CI runs Python 3.10, 3.11 and 3.12.
