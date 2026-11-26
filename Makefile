.PHONY: check test

check:
	uv lock --check
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked mypy
	uv run --locked pytest

test:
	uv run --locked pytest
