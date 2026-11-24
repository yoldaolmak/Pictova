# Pictova

Local WordPress image-placement tool for travel publishing. Pictova finds
existing photographs for article sections, prepares WebP files and editorial
metadata, and inserts images into Gutenberg with placement verification.

Pictova grew out of the day-to-day editorial needs of [yoldaolmak.com](https://yoldaolmak.com).

## Get started

Python 3.10–3.12 · macOS or Linux · WordPress Application Password

```bash
git clone https://github.com/yoldaolmak/Pictova.git
cd Pictova
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
pictova health
pictova studio
```

Configure the authorized editorial account and intended image sources before
opening a post. Inspect candidate previews and heading assignments, reject
unsuitable images, then explicitly approve insertion. Licensed stock requires
separate consent.

- Match the subject of each H2/H3; leave unmatched sections empty.
- Use existing photographs. Metadata alone is not proof of image identity.
- Review and plan do not purchase licenses or modify WordPress.
  Processing may download licensed media; attach writes to WordPress.
- Verify inserted blocks and managed-media ownership. Inspect partial or
  interrupted receipts before retrying.

[Documentation](docs/README.md) · [CLI](docs/reference/cli.md) ·
[Architecture](docs/architecture/overview.md) · [Security](SECURITY.md)

MIT licensed. See [LICENSE](LICENSE).
