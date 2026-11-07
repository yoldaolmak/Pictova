# Contributing

Pictova is an independent image-selection and WordPress placement tool. New work belongs in the native `src/pictova/` engine and app; `src/core/` and `src/main.py` are compatibility code.

## Setup and checks

```bash
pip install -e '.[dev]'
python -m pytest -q
python -m flake8 src/ --max-line-length=120
python -m black --check --line-length 120 src/
node --check src/pictova/app/static/studio.js
```

Use a feature branch from `main`. Keep a PR focused on one product behavior. Add a regression for the successful case **and** for the wrong image or unsafe write being rejected.

## Boundaries

- The target heading, not the post title or an expanded model query, determines image identity.
- Missing evidence leaves the placement empty. Do not invent place aliases.
- A preview must not write to WordPress or quietly purchase a stock license.
- Preserve non-Pictova Gutenberg blocks. Refuse ambiguous edits.
- Keep existing CLI result and argument contracts compatible.
- Never put credentials, private photo paths or raw post content in tests or issue reports.

Update only the relevant documentation and `CHANGELOG.md`. Describe verified behavior, not intended capability. CI uses mocked integrations and does not prove real-world visual accuracy or a live publish.

For source integrations, see [Adding sources](docs/guides/adding-sources.md). For trust limits, see [Security](SECURITY.md).
