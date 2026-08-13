# Site Configuration

The supported WordPress sites are defined by the adapter’s configured endpoint
names:

| CLI value | Environment prefix |
|---|---|
| `yoldaolmak` | `WP_` |
| `gezievreni` | `GEZIEVRENI_` |
| `gezgindunyasi` | `GEZGINDUNYASI_` |
| `auto` | Resolves a post across the configured sites, fail-closed on ambiguity |

The native engine applies shared selection, metadata, and placement policy to
all sites. A new site requires an explicit adapter configuration and tests for
credentials, post resolution, and managed-media writes; it is not enabled by
adding an untested Python profile file.

Use an explicit site for production operations whenever possible:

```bash
pictova plan --site gezievreni --post 173613 --count 4
```
