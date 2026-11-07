# Tests

```bash
python3 -m pytest -q
python3 -m pytest tests/unit/test_studio.py -q
python3 -m pytest tests/unit/test_synthetic_model_contract.py -q
```

`tests/unit/` covers image selection, rejection, metadata, WordPress media ownership, Studio security and providers. `tests/integration/` verifies CLI contracts without live WordPress credentials.

All external model, paid-provider and WordPress interactions in CI use controlled fixtures or mocks. The synthetic OpenAI-compatible response tests verify transport and fail-closed behavior, **not** classification of actual image pixels.

Expected failures (`xfail`) document unresolved behavior; do not treat them as passing capabilities. CI runs Python 3.10, 3.11 and 3.12.
