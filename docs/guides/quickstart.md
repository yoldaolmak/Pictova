# Quickstart

Inspect an image plan before making a WordPress change. Pictova will return
fewer images than requested when it cannot match the article's sections.

## Requirements

Python 3.10+, a configured WordPress site and at least one intended image
source. A Mac Photos index and DepositPhotos credentials are optional.

## Install

```bash
git clone https://github.com/yoldaolmak/Pictova.git
cd Pictova
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

Fill in only the WordPress profile and source settings you will actually use.
Never commit `.env`. For the supported site variables, see
[WordPress Setup](wordpress-setup.md) and
[Configuration](../reference/configuration.md).

## Check the environment

```bash
pictova health
```

The JSON contains `status`, module readiness, `photo_index`, `vision_chain`
and `wordpress_sites`. An overall `ok` does not certify that a specific
post is readable or that a source will return exact images.

## Review and plan

```bash
pictova review --site yoldaolmak --post 265713
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
```

Check the heading assignments, selected candidates and warnings. An empty
list can mean no candidate supported the named subject, not a broken run.

## Process and publish

```bash
# Download/prepare locally; does not change WordPress.
pictova process --site yoldaolmak --post 265713 --count 4 --source auto

# Writes to WordPress. Run only after reviewing the plan.
pictova attach --site yoldaolmak --post 265713 --count 4 --source auto --engine native
```

A request for four images may select fewer or none. Do not bypass exact
matching or the quality gate to reach a count.

For authenticated local automation, see the
[HTTP API Reference](../reference/http-api.md).
