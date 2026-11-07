# Pictova developer commands. Uses the same formatting limits as CI.

.PHONY: help install install-dev test test-unit lint format studio run clean

help:
	@printf 'Pictova: install | install-dev | test | test-unit | lint | format | studio | run POST_ID=<id> | clean\n'

install:
	python -m pip install -e .

install-dev:
	python -m pip install -e '.[dev]'

test:
	python -m pytest tests/ -q

test-unit:
	python -m pytest tests/unit/ -q

lint:
	python -m flake8 src/ --max-line-length=120
	python -m black --check --line-length 120 src/
	node --check src/pictova/app/static/studio.js

format:
	python -m black --line-length 120 src/

studio:
	pictova studio

# Compatibility convenience command; WordPress writes occur only after this command.
run:
	@test -n "$(POST_ID)" || (echo "Usage: make run POST_ID=<id> [SITE=yoldaolmak]" && exit 2)
	pictova attach --post "$(POST_ID)" --site "$(or $(SITE),auto)" --source auto --engine native

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache htmlcov build dist
