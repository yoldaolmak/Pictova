# Contributing

## Naming Convention

All code and documentation must use **Pictova** as the product name, `pictova` as the CLI command, and `src.pictova` as the Python package root. See [Brand & Naming Doctrine](docs/architecture/naming.md).

## Branch and Commit

- Branch from `main`
- Commit messages: `type: short description` (feat, fix, docs, refactor, test, ops)
- Every completed change must be committed and pushed — unpushed work is not done

## Adding a Feature

1. Update `CHANGELOG.md` under `[Unreleased]` when the change is user-visible
2. Write or update tests in `tests/`
3. Run `python3.10 -m pytest -q` — all must pass
4. Update relevant `docs/` page

## Adding an Image Source

1. Implement `src/pictova/providers/mysource.py` — see [Adding Sources](docs/guides/adding-sources.md)
2. Register the provider in the native selector/provider boundary
3. Add focused tests that prove strict matching and fail-closed behavior
4. Update `docs/guides/adding-sources.md` and `docs/concepts/sources.md`

## Architecture Rules

- App layer (`src/pictova/app/`) contains no selection or publishing policy
- Native engine and providers own the supported production path
- New behavior must not bypass Pictova through one-off WordPress or provider scripts
- Do not add new code to `src/core/` or `src/main.py`; migrate it into `src/pictova/engine/` instead

## Testing

```bash
python3.10 -m pytest -q              # run all tests
python3.10 -m pytest tests/unit/     # unit only
python3.10 -m pytest tests/integration/  # integration only
```

Integration tests require no WordPress credentials — they test the CLI contract with structured failure responses.

## Documentation

- All docs are in English
- Every new feature needs at least one updated doc page
- Concepts = what/why; Guides = how; Reference = complete spec; Architecture = design decisions
