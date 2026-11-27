.PHONY: env check test e2e

env:
	@if [ -e .env ]; then echo ".env уже существует, не перезаписываю."; exit 1; fi
	@umask 077; sed \
		-e "s|^APP_ACCESS_KEY=.*|APP_ACCESS_KEY=$$(openssl rand -hex 16)|" \
		-e "s|^APP_SESSION_SECRET=.*|APP_SESSION_SECRET=$$(openssl rand -hex 32)|" \
		-e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$$(openssl rand -hex 32)|" \
		.env.example > .env
	@echo "Создан .env (права 0600). Заполните APP_LLM__BASE_URL, APP_LLM__MODEL и LLM_API_KEY."
	@echo "Ключ для входа в браузере: grep APP_ACCESS_KEY .env"

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
