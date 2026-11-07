# Native and Legacy Paths

The **native** engine is the supported publishing route:

```bash
pictova plan --site yoldaolmak --post 265713 --engine native --source auto
pictova attach --site yoldaolmak --post 265713 --engine native --source auto
```

It coordinates heading-specific selection, media processing, metadata, quality
validation, Gutenberg insertion and managed-media checks.

The CLI currently also accepts `--engine legacy`. That path calls
`YOOrchestrator` from `src/main.py` and retains older behavior for
compatibility. It does not have equivalent fail-closed semantic and publishing
guarantees. Do not describe it as a second production-ready path or build new
features on it.

When migration still requires a legacy helper, invoke it through the native
engine behind a regression-tested interface. Do not create an alternate direct
WordPress write script or bypass selection to complete a specific post.
