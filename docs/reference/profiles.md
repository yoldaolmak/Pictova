# Site configuration

Use the primary editorial profile (`--site yoldaolmak`) for ordinary work.
Its endpoint and credentials come from `WP_URL`, `WP_USER` and
`WP_APP_PASSWORD`.

Existing installations may retain these compatibility settings:

| CLI key | Environment prefix |
| --- | --- |
| `gezievreni` | `GEZIEVRENI_` |
| `gezgindunyasi` | `GEZGINDUNYASI_` |

`--site auto` resolves a post across configured profiles and refuses
ambiguous IDs. Use an explicit profile for writes. Configure only authorized
accounts.

See [Configuration](configuration.md).
