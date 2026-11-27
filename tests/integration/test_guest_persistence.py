import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from themed_chat.adapters.database import migrate_database
from themed_chat.app import create_app
from themed_chat.settings import (
    AppSettings,
    ModelSettings,
    SecretSettings,
    Settings,
)

ORIGIN = "http://127.0.0.1:8000"
ACCESS_KEY = "sql_fixture_key"


@pytest.mark.anyio
async def test_guest_survives_application_restart(postgres_dsn: SecretStr) -> None:
    settings = Settings(
        AppSettings(llm=ModelSettings(model="test", system_prompt="test")),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr(ACCESS_KEY),
            APP_SESSION_SECRET=SecretStr("long-test-secret-for-session-signatures"),
            GEMINI_API_KEY=SecretStr("fixture-key"),
            DATABASE_URL=postgres_dsn,
        ),
    )
    first = create_app(settings)
    headers = {"Origin": ORIGIN, "X-Access-Key": ACCESS_KEY}
    async with (
        first.router.lifespan_context(first),
        AsyncClient(transport=ASGITransport(first), base_url=ORIGIN) as browser,
    ):
        assert (await browser.post("/api/session", headers=headers)).status_code == 204
        cookies = browser.cookies

    second = create_app(settings)
    async with (
        second.router.lifespan_context(second),
        AsyncClient(transport=ASGITransport(second), base_url=ORIGIN, cookies=cookies) as browser,
    ):
        assert (await browser.get("/api/session")).status_code == 204
        assert (await browser.post("/api/session", headers=headers)).status_code == 204

    engine = create_async_engine(postgres_dsn.get_secret_value())
    try:
        async with engine.connect() as connection:
            rows = (await connection.execute(text("SELECT id, created_at FROM users"))).all()
        assert len(rows) == 1
        assert rows[0].id.version == 4
        assert rows[0].created_at
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_interrupted_migration_rolls_back_before_retry(postgres_dsn: SecretStr) -> None:
    engine = create_async_engine(postgres_dsn.get_secret_value())

    def fail_before_stamp(
        _connection: object, _cursor: object, statement: str, *_rest: object
    ) -> None:
        if statement.startswith("INSERT INTO alembic_version"):
            raise RuntimeError("injected failure before migration stamp")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_before_stamp)
    try:
        with pytest.raises(RuntimeError, match="injected failure"):
            await migrate_database(engine)
        event.remove(engine.sync_engine, "before_cursor_execute", fail_before_stamp)
        await migrate_database(engine)
        async with engine.connect() as connection:
            version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == "0002_chat_turns"
    finally:
        await engine.dispose()
