# Configuration

Pictova reads environment variables and the repository's optional `.env`. Copy `.env.example`; never commit real credentials.

## WordPress

| Variable | Use |
| --- | --- |
| `WP_URL`, `WP_USER`, `WP_APP_PASSWORD` | `yoldaolmak` profile |
| `GEZIEVRENI_URL`, `GEZIEVRENI_USER`, `GEZIEVRENI_PASS` | `gezievreni` profile |
| `GEZGINDUNYASI_URL`, `GEZGINDUNYASI_USER`, `GEZGINDUNYASI_PASS` | `gezgindunyasi` profile |

Use WordPress Application Passwords, not your normal login password. `WP_PASSWORD` is a legacy alias for `WP_APP_PASSWORD`.

## Image sources and vision

| Variable | Use |
| --- | --- |
| `YO_VISUAL_MEMORY_DB` | SQLite image index (default: `data/visual_memory.db`) |
| `UNSPLASH_ACCESS_KEY` | Unsplash |
| `DEPOSIT_API_KEY`, `DEPOSIT_LOGIN_USER`, `DEPOSIT_LOGIN_PASSWORD` | Licensed DepositPhotos |
| `GEMINI_API_KEY` or `GEMINI_API_KEYS` | Gemini; multi-key value is comma-separated |
| `GEMINI_VISION_MODEL` | Optional Gemini model override |
| `OPENAI_API_KEY` | Optional vision fallback |
| `PICTOVA_VISION_DAILY_LIMIT` | Completed scans per day (default 1350; `0` removes the cap) |

The local LM Studio option can run without an API key. A cached or available vision model is needed for native visual metadata; synthetic CI fixtures are not a real model.

## Local HTTP and Studio

`PICTOVA_HTTP_TOKEN`: at least 32 ASCII characters for `pictova serve` and `pictova studio --no-open`. Plain `pictova studio` can create a temporary token and launch the browser.

HTTP bind host and port are CLI flags, not environment defaults. The server is loopback-only.

Use `pictova health` to inspect configured source readiness. It does not validate individual image identity or a live WordPress publish.
