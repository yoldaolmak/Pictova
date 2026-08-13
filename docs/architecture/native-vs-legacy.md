# Native and Legacy Paths

The supported production path is the native engine:

```bash
pictova attach --site yoldaolmak --post 265713 --engine native
```

It owns strict source selection, metadata policy, Gutenberg placement, media
verification, and the managed-media guard. The CLI defaults to `native`.

`src/main.py` and selected `src/core/` modules remain only as compatibility
dependencies while their callers are retired. They are not a second publishing
surface and new functionality must not be added there.

## Migration rule

When a legacy helper is still required, wrap or call it from the native engine
behind a tested contract. Do not recreate legacy behavior in a one-off script,
and do not bypass selection or publishing checks for a one-off post.
