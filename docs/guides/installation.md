# Installation

## System Requirements

- macOS or Linux
- Python 3.10–3.12 (CI-tested)
- WordPress 5.8+ with Application Passwords enabled
- (Optional) Mac Photos library for visual memory

## Step 1: Clone the Repository

```bash
git clone https://github.com/yoldaolmak/Pictova.git
cd Pictova
```

## Step 2: Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Step 3: Install Dependencies

```bash
pip install -e .
```

`-e` installs the CLI and runtime dependencies. For tests and lint, use `pip install -e '.[dev]'`.

On macOS, install Photos-library support only if you will index Mac Photos:

```bash
pip install -e '.[macos]'
```

## Step 4: Configure Environment

```bash
cp .env.example .env
```

### Minimum Configuration

```bash
# WordPress — required for the yoldaolmak profile
WP_USER=your-wordpress-username
WP_APP_PASSWORD=your-app-password

# One intended image source, if using Unsplash
UNSPLASH_ACCESS_KEY=your-unsplash-key
```

### Full Configuration

See [Configuration Reference](../reference/configuration.md) for all available variables.

## Step 5: Verify Installation

```bash
pictova health
```

The health JSON reports module readiness, indexed photo counts, vision sources,
and configured WordPress sites. `status: ok` does not guarantee that a specific post or provider is accessible.

```bash
pip install -e '.[dev]'
python3 -m pytest -q
```

Expected: passing tests and explicitly reported `xfail` cases. CI does not run live WordPress tests.

## Optional: Mac Photos Visual Memory

Index the Mac Photos library separately if you intend to use it.

See [Mac Photos Setup](mac-photos-setup.md) for the full guide.

Once indexed, add to `.env`:

```bash
YO_VISUAL_MEMORY_DB=/absolute/path/to/visual_memory.db
```

## Optional: HTTP Service

To run Pictova as an HTTP service:

```bash
export PICTOVA_HTTP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
pictova serve --host 127.0.0.1 --port 8040
```

See [HTTP API Reference](../reference/http-api.md) for endpoint documentation.

## Troubleshooting

**`pictova: command not found`**  
Make sure your virtualenv is active and you ran `pip install -e .`.

**`review` returns an auth error**  
Verify `WP_USER` and `WP_APP_PASSWORD`. Application Password format: `xxxx xxxx xxxx xxxx xxxx xxxx`.

**`plan` returns empty candidates**  
Either the selected provider is not configured, or `YO_VISUAL_MEMORY_DB` points
to an empty/nonexistent database. Run `pictova health` and inspect the returned
source status.
