from pathlib import Path

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

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
