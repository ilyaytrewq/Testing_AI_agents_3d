FROM ghcr.io/astral-sh/uv:0.13.3 AS uv
FROM python:3.13-slim

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --locked --no-dev --no-editable \
    && mkdir /data \
    && chown 10001:10001 /data

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "themed_chat.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--ws", "none"]
