# Operations

## Preview

```bash
pictova health
pictova review --site yoldaolmak --post 265713
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
```

Inspect target headings, candidate evidence and warnings. A missing exact match is not a failure to be filled with a generic image.

## Process and publish

```bash
pictova process --site yoldaolmak --post 265713 --count 4 --source auto
pictova attach --site yoldaolmak --post 265713 --count 4 --source auto --engine native
```

`process` can download/licence images but does not alter WordPress. `attach` writes. For interactive approval of exact candidates, use `pictova studio`.

Inspect managed media without a write:

```bash
pictova guard --site yoldaolmak --post 265713
```

`guard --repair`, `--reposition`, `--adopt` and `--reset` write. Back up the post first. Mixed-ownership galleries are rejected rather than deleted.

## Diagnose

- **No images:** Check exact heading matches, source configuration and `warnings`.
- **Provider failure:** Check connectivity and credentials. Never repeat a licensed download blindly.
- **Failed quality gate:** Review the original file and metadata; do not bypass the gate.
- **WordPress failure:** Check the selected profile, application password, inserted-block count and operation receipt. An uploaded media ID is not proof of publication.
- **Partial/interrupted job:** Inspect WordPress, managed-media manifest and local receipt before retrying. Media uploaded without confirmed metadata or association may require orphan cleanup. Partial is not success; interrupted jobs are never automatically resumed.
- **Manifest drift:** Reposition or repair only managed image blocks after reviewing the affected headings and mixed-ownership galleries.

```bash
python3 -m pytest -q
```

Offline tests cannot validate live WordPress publication or real image identity. For index operations see [Indexing](indexing.md); for authenticated local HTTP see [API](../reference/http-api.md).
