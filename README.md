# Pictova

Pictova finds, checks, prepares and places existing images in WordPress articles. Selection is based on the target H2/H3 section, not just the article's destination. If a named subject cannot be matched, the section stays empty.

Independent Python application · Local Studio · CLI · WordPress Gutenberg

## Quick start

Requires Python 3.10–3.12 and a configured WordPress Application Password.

```bash
git clone https://github.com/yoldaolmak/Pictova.git
cd Pictova
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
pictova health
```

Configure the required values in `.env` before using a real post.

**Studio — interactive review**

```bash
pictova studio
```

Paste a configured WordPress post URL → inspect image previews and proposed headings → reject candidates → explicitly approve publication. Paid stock downloads require separate consent. Studio is local-only.

**CLI — scripted workflow**

```bash
pictova review --site yoldaolmak --post 265713
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
pictova process --site yoldaolmak --post 265713 --count 4 --source auto
pictova attach --site yoldaolmak --post 265713 --count 4 --source auto --engine native
```

`review` and `plan` do not modify WordPress or buy licenses. `process` can download images, including licensed assets, but does not publish. `attach` writes to WordPress. The existing `guard` command has separate explicit write modes.

## Boundaries

- Local Visual Memory / Mac Photos and configured external image providers.
- Heading-aware matching, image processing, visual metadata and guarded Gutenberg placement.
- No image generation. Candidate metadata is **not** proof of what an image depicts.
- Missing matches remain empty. CLI direct-source and legacy paths do not share every native selection guarantee.
- CI verifies offline contracts, **not** real-world place identification or a live WordPress deployment.

## Development

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
```

CI tests Python 3.10, 3.11 and 3.12, checks Flake8/Black, and checks Studio JavaScript syntax.

A media upload is not a successful publication until WordPress content and
managed-media placement are verified. Partial and interrupted jobs require
operator inspection before retrying; see [Operation lifecycles](docs/architecture/lifecycles.md).

[Studio](docs/guides/studio.md) · [CLI](docs/reference/cli.md) · [Configuration](docs/reference/configuration.md) · [Architecture](docs/architecture/overview.md) · [Security](SECURITY.md) · [Documentation index](docs/README.md) · [Contributing](CONTRIBUTING.md)

MIT licensed. See [LICENSE](LICENSE).
