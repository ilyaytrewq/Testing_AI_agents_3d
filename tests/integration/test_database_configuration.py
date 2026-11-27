import traceback
from pathlib import Path

import pytest
from pydantic import SecretStr

from themed_chat.adapters.database import create_database_engine
from themed_chat.app import create_app
from themed_chat.settings import (
    AppSettings,
    ConfigurationError,
    ModelSettings,
    SecretSettings,
    Settings,
    load_settings,
)


@pytest.fixture
def deployment_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name, value in {
        "APP_ACCESS_KEY": "compose_fixture_key",
        "APP_SESSION_SECRET": "test-database-signing-secret-not-production",
        "APP_LLM__BASE_URL": "https://llm.test/v1",
        "APP_LLM__MODEL": "fixture",
        "LLM_API_KEY": "unused-fixture",
    }.items():
        monkeypatch.setenv(name, value)
    return tmp_path / ".env"


@pytest.fixture
def cloud_env(deployment_env: Path) -> Path:
    deployment_env.write_text(
        "DATABASE_URL=postgresql+asyncpg://test:fixture@database.test:5432/chat?ssl=verify-full\n"
    )
    return deployment_env


@pytest.mark.anyio
async def test_reads_postgresql_dsn_from_dotenv(cloud_env: Path) -> None:
    engine = create_database_engine(load_settings(env_file=cloud_env))
    try:
        assert engine.url.drivername == "postgresql+asyncpg"
        assert engine.url.host == "database.test"
    finally:
        await engine.dispose()


def test_application_requires_postgresql_dsn_even_with_a_legacy_file_path(
    deployment_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DB__SQLITE_PATH", "/data/chat.sqlite3")
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        create_app(load_settings(env_file=deployment_env))


def postgres_settings(url: str) -> Settings:
    return Settings(
        AppSettings(
            llm=ModelSettings(base_url="https://unused.test/v1", model="test", system_prompt="test")
        ),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr("postgres_fixture_key"),
            APP_SESSION_SECRET=SecretStr("fixture-session-secret-not-for-production"),
            LLM_API_KEY=SecretStr("unused"),
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


@pytest.mark.anyio
async def test_unreachable_database_is_service_unavailable() -> None:
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from support import LOGIN, ORIGIN, WRITE, MemoryStorage, StubGenerator, make_settings

    from themed_chat.adapters.sql_repository import (
        SqlChatRepository,
        SqlGuestRepository,
        SqlSessionRepository,
    )
    from themed_chat.app import Overrides, Storage

    # Port 1 on loopback refuses connections: asyncpg raises outside SQLAlchemy's wrapping.
    settings = make_settings(database_url="postgresql+asyncpg://test:secret@127.0.0.1:1/x")
    engine = create_database_engine(settings)
    sessions = async_sessionmaker(engine)
    try:
        down = Storage(
            SqlGuestRepository(sessions),
            SqlChatRepository(sessions),
            SqlSessionRepository(sessions),
        )
        memory = MemoryStorage()
        guests_up = Storage(memory, SqlChatRepository(sessions), memory)
        for storage, checks in ((down, ["login"]), (guests_up, ["read", "send"])):
            app = create_app(settings, Overrides(storage, StubGenerator()))
            transport = ASGITransport(app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url=ORIGIN) as client:
                login = await client.post("/api/session", headers=LOGIN)
                responses = {"login": login}
                if "read" in checks:
                    responses["read"] = await client.get("/api/messages")
                    responses["send"] = await client.post(
                        "/api/messages", headers=WRITE, json={"text": "кофе"}
                    )
                for name in checks:
                    assert responses[name].status_code == 503, name
                    assert responses[name].json() == {"error": {"code": "service_unavailable"}}
    finally:
        await engine.dispose()
