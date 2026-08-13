# Configuration Reference

All configuration is via environment variables, loaded from `.env` in the repo root.

## WordPress

| Variable | Required | Description |
|----------|----------|-------------|
| `WP_USER` | Yes for yoldaolmak | WordPress username |
| `WP_APP_PASSWORD` | Yes for yoldaolmak | WordPress Application Password (`WP_PASSWORD` remains a legacy alias) |
| `GEZIEVRENI_USER` / `GEZIEVRENI_PASS` | Yes for gezievreni | Site username and Application Password |
| `GEZGINDUNYASI_USER` / `GEZGINDUNYASI_PASS` | Yes for gezgindunyasi | Site username and Application Password |

## Image Sources

| Variable | Required | Description |
|----------|----------|-------------|
| `UNSPLASH_ACCESS_KEY` | For Unsplash source | Unsplash API access key |
| `DEPOSIT_API_KEY` | For Deposit source | DepositPhotos API key |
| `DEPOSIT_LOGIN_USER` / `DEPOSIT_LOGIN_PASSWORD` | For Deposit download | DepositPhotos account credentials |
| `YO_VISUAL_MEMORY_DB` | For semantic source | Path to visual memory SQLite database |

## AI / Vision

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` or `GEMINI_API_KEYS` | No | Gemini Flash vision provider; comma-separate multiple keys |
| `OPENAI_API_KEY` | No | Low-cost vision fallback |
| `ANTHROPIC_API_KEY` | No | Enables Claude CLI/API fallback where configured |

For native attachment, Pictova first reuses completed Visual Memory metadata.
If no usable cache entry exists, it requires an available vision provider; it
fails closed rather than fabricating descriptive metadata.

## Local Index

| Variable | Default | Description |
|----------|---------|-------------|
| `YO_VISUAL_MEMORY_DB` | `data/visual_memory.db` | Local semantic image index |

## HTTP Server

| Variable | Default | Description |
|----------|---------|-------------|
| `PICTOVA_HOST` | `127.0.0.1` | Default bind address for `pictova serve` |
| `PICTOVA_PORT` | `8040` | Default port |

## Defaults

| Variable | Default | Description |
|----------|---------|-------------|
| `PICTOVA_DEFAULT_COUNT` | `4` | Images per post when `--count` is omitted |
| `PICTOVA_VISION_DAILY_LIMIT` | `1350` | Maximum completed Vision scans per calendar day; `0` disables the guard |

## Example .env

```bash
# WordPress
WP_USER=myusername
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx

# Image sources
UNSPLASH_ACCESS_KEY=abc123
YO_VISUAL_MEMORY_DB=/Users/yoldaolmak/Projects/Pictova/data/visual_memory.db

# Vision (optional, improves metadata quality)
GEMINI_API_KEY=...
OPENAI_API_KEY=...

# Server
PICTOVA_PORT=8040
```
