.PHONY: test test-lima lint build pex docs docs-build clean

test:
	uv run pytest

test-lima:
	uv run pytest -m lima -v

lint:
	uvx ruff check src tests
	uvx ruff format --check src tests

build:
	uv build

pex:
	uv run pex . -c lima-ai --scie eager -o dist/lima-ai

clean:
	rm -rf dist

docs:
	uv run --with-requirements docs/manual/requirements.txt mkdocs serve -f docs/manual/mkdocs.yml

docs-build:
	uv run --with-requirements docs/manual/requirements.txt mkdocs build --strict -f docs/manual/mkdocs.yml
