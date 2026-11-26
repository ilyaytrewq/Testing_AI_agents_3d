.PHONY: check test e2e

check:
	uv lock --check
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked mypy
	uv run --locked pytest

test:
	uv run --locked pytest

e2e:
	uv run --locked --group browser pytest tests/e2e
