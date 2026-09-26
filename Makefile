.PHONY: test test-lima lint pex clean

test:
	uv run pytest

test-lima:
	uv run pytest -m lima -v

lint:
	uvx ruff check src tests
	uvx ruff format --check src tests

pex:
	uv run pex . -c lima-ai --scie eager -o dist/lima-ai

clean:
	rm -rf dist
