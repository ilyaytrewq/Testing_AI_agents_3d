from pathlib import Path

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

from themed_chat.adapters.database import migrate_database
from themed_chat.app import create_app
from themed_chat.settings import (
    AppSettings,
    DatabaseSettings,
    ModelSettings,
    SecretSettings,
    Settings,
)

ORIGIN = "http://127.0.0.1:8000"
ACCESS_KEY = "sql_fixture_key"


@pytest.mark.anyio
async def test_guest_survives_application_restart(tmp_path: Path) -> None:
    database = tmp_path / "nested" / "chat.sqlite3"
    settings = Settings(
        AppSettings(
            llm=ModelSettings(model="test", system_prompt="test"),
            db=DatabaseSettings(sqlite_path=database),
        ),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr(ACCESS_KEY),
            APP_SESSION_SECRET=SecretStr("long-test-secret-for-session-signatures"),
            GEMINI_API_KEY=SecretStr("fixture-key"),
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
    assert database.is_file()

    second = create_app(settings)
    async with (
        second.router.lifespan_context(second),
        AsyncClient(transport=ASGITransport(second), base_url=ORIGIN, cookies=cookies) as browser,
    ):
        assert (await browser.get("/api/session")).status_code == 204
        assert (await browser.post("/api/session", headers=headers)).status_code == 204

    async with aiosqlite.connect(database) as connection:
        async with connection.execute("SELECT id, created_at FROM users") as cursor:
            rows = await cursor.fetchall()
        assert len(rows) == 1
        assert len(rows[0][0]) == 32
        assert rows[0][1]


@pytest.mark.anyio
async def test_interrupted_migration_rolls_back_before_retry(tmp_path: Path) -> None:
    database = tmp_path / "migration.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")

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
        async with (
            aiosqlite.connect(database) as connection,
            connection.execute("SELECT version_num FROM alembic_version") as cursor,
        ):
            assert (await cursor.fetchone()) == ("0001_users",)
    finally:
        await engine.dispose()
