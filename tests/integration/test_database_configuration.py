import traceback
from pathlib import Path

import pytest
from pydantic import SecretStr

from themed_chat.adapters.database import create_database_engine
from themed_chat.app import create_app
from themed_chat.settings import (
    AppSettings,
    ConfigurationError,
    DatabaseSettings,
    ModelSettings,
    SecretSettings,
    Settings,
    load_settings,
)


@pytest.fixture
def deployment_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("APP_DB__BACKEND", "APP_DB__SQLITE_PATH", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "APP_ACCESS_KEY": "compose_fixture_key",
        "APP_SESSION_SECRET": "test-database-signing-secret-not-production",
        "GEMINI_API_KEY": "unused-fixture",
    }.items():
        monkeypatch.setenv(name, value)
    return tmp_path / ".env"


@pytest.fixture
def cloud_env(deployment_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    deployment_env.write_text(
        "DATABASE_URL=postgresql+asyncpg://test:fixture@database.test:5432/chat?ssl=verify-full\n"
    )
    monkeypatch.setenv("APP_DB__SQLITE_PATH", "/data/chat.sqlite3")
    return deployment_env


@pytest.mark.anyio
async def test_dsn_selects_postgresql_even_with_compose_sqlite_path(cloud_env: Path) -> None:
    engine = create_database_engine(load_settings(env_file=cloud_env))
    try:
        assert engine.url.drivername == "postgresql+asyncpg"
        assert engine.url.host == "database.test"
    finally:
        await engine.dispose()


def test_explicit_sqlite_rejects_a_postgresql_dsn(
    deployment_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DB__BACKEND", "sqlite")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:fixture@database.test/chat")
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        create_app(load_settings(env_file=deployment_env))


def test_sqlite_requires_an_explicit_storage_path(deployment_env: Path) -> None:
    with pytest.raises(ConfigurationError, match="APP_DB__SQLITE_PATH"):
        create_app(load_settings(env_file=deployment_env))


@pytest.mark.anyio
async def test_compose_path_selects_sqlite_without_a_dsn(
    deployment_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DB__SQLITE_PATH", "/data/chat.sqlite3")
    engine = create_database_engine(load_settings(env_file=deployment_env))
    try:
        assert (engine.url.drivername, engine.url.database) == (
            "sqlite+aiosqlite",
            "/data/chat.sqlite3",
        )
    finally:
        await engine.dispose()


def postgres_settings(url: str) -> Settings:
    return Settings(
        AppSettings(
            db=DatabaseSettings(backend="postgresql"),
            llm=ModelSettings(model="test", system_prompt="test"),
        ),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr("postgres_fixture_key"),
            APP_SESSION_SECRET=SecretStr("fixture-session-secret-not-for-production"),
            GEMINI_API_KEY=SecretStr("unused"),
            DATABASE_URL=SecretStr(url),
        ),
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        ":1/fixture?target_session_attrs=test-private-marker",
        ":1/fixture?password=test-private-marker",
        ":1/fixture?ssl=test-private-marker",
        ":1/fixture?sslmode=require",
        ":65536/fixture",
    ],
)
def test_rejects_bad_postgresql_options_without_printing_dsn(endpoint: str) -> None:
    settings = postgres_settings(f"postgresql+asyncpg://test:secret@127.0.0.1{endpoint}")
    with pytest.raises(ConfigurationError, match="DATABASE_URL") as caught:
        create_database_engine(settings)
    assert "test-private-marker" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.anyio
async def test_startup_does_not_echo_raw_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_migration(_engine: object) -> None:
        raise OSError("test-private-marker")

    monkeypatch.setattr("themed_chat.app.migrate_database", fail_migration)
    app = create_app(postgres_settings("postgresql+asyncpg://test:secret@127.0.0.1:1/fixture"))
    with pytest.raises(ConfigurationError, match="PostgreSQL") as caught:
        async with app.router.lifespan_context(app):
            pytest.fail("Startup should have been aborted.")
    assert "test-private-marker" not in "".join(traceback.format_exception(caught.value))
