# Engine Modules

The native engine lives under `src/pictova/engine/`. Its public flow is:

```text
post context → selector → processor → metadata → publisher → verification
```

| Module | Responsibility |
|---|---|
| `attach.py` | Coordinates a plan, process, attach, and result receipt. |
| `selector.py` | Chooses exact heading-aware candidates and handles source fallback. |
| `processor.py` | Converts selected files to the publishable format. |
| `metadata.py` | Separates visual evidence from article-aware SEO metadata and captions. |
| `placement.py` | Applies measured heading and gallery policy. |
| `publisher.py` | Hands validated media to the WordPress adapter. |
| `gallery.py` | Searches the local visual index and constructs native gallery data. |

The WordPress adapter and managed-media verification live in
`src/services/wordpress.py`. Provider-specific network operations live in
`src/pictova/providers/`.

## Invariants

- A named heading needs an exact candidate or remains unfilled.
- A caption uses article copy when available; it is not a raw visual inventory.
- A gallery is a placement decision, not a side effect of requested image count.
- An anchored media block is verified after a WordPress write.
