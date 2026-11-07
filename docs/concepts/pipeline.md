# Workflow

| Stage | Result | WordPress write? |
| --- | --- | --- |
| `review` | Post, title and headings | No |
| `plan` | Candidates, heading assignments, warnings | No |
| `process` | Prepared local files; may download/license images | No |
| `attach` | Uploaded media, Gutenberg blocks, verification | **Yes** |

```bash
pictova review --site yoldaolmak --post 265713
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
pictova process --site yoldaolmak --post 265713 --count 4 --source auto
pictova attach --site yoldaolmak --post 265713 --count 4 --source auto --engine native
```

A requested count is an upper bound. Empty sections are preferable to unrelated images. The plan is a preview; CLI `attach` re-runs selection. For exact human-approved candidates, use [Studio](../guides/studio.md), which binds publication to a single-use plan.

The legacy engine remains for compatibility but lacks the native path's full safeguards. See [Native vs. legacy](../architecture/native-vs-legacy.md).
