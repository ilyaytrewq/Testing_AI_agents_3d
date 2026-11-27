import logging

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError
from support import LOGIN, ORIGIN, MemoryStorage, StubGenerator, make_settings

from themed_chat.adapters.sql_repository import storage_errors
from themed_chat.app import create_app
from themed_chat.chat.errors import StorageUnavailable


def failing(error: Exception) -> object:
    @storage_errors
    async def operation() -> None:
        raise error

    return operation


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("down")),
        ConnectionRefusedError("refused"),
        DBAPIError("SELECT 1", {}, Exception("gone"), connection_invalidated=True),
    ],
)
async def test_connection_failures_become_storage_unavailable(error: Exception) -> None:
    with pytest.raises(StorageUnavailable):
        await failing(error)()  # type: ignore[operator]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [
        IntegrityError("INSERT", {}, Exception("duplicate")),
        ProgrammingError("SELECT", {}, Exception("syntax")),
        DBAPIError("SELECT 1", {}, Exception("bad"), connection_invalidated=False),
    ],
)
async def test_other_database_errors_are_not_hidden(error: Exception) -> None:
    with pytest.raises(type(error)):
        await failing(error)()  # type: ignore[operator]


class FakeAsyncpgError(Exception):
    sqlstate = "23505"
    constraint_name = "chat_turns_pkey"


@pytest.mark.anyio
async def test_a_database_bug_is_logged_without_row_contents(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = MemoryStorage()
    private = "Key (question)=(private user text) already exists"

    async def broken(**_: object) -> int:
        cause = FakeAsyncpgError(private)
        orig = Exception(private)
        orig.__cause__ = cause
        raise IntegrityError("INSERT INTO chat_turns", {"question": "private user text"}, orig)

    storage.latest_revision = broken  # type: ignore[method-assign,assignment]
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    caplog.set_level(logging.ERROR)
    transport = ASGITransport(app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=ORIGIN) as client:
        await client.post("/api/session", headers=LOGIN)
        response = await client.get("/api/messages")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error"}}
    [record] = [r for r in caplog.records if "Unhandled error" in r.getMessage()]
    assert record.exc_info is None
    assert "IntegrityError sqlstate=23505 constraint=chat_turns_pkey" in record.getMessage()
    assert "private user text" not in caplog.text


@pytest.mark.anyio
async def test_other_bugs_keep_their_traceback(caplog: pytest.LogCaptureFixture) -> None:
    storage = MemoryStorage()

    async def broken(**_: object) -> int:
        raise RuntimeError("boom")

    storage.latest_revision = broken  # type: ignore[method-assign,assignment]
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    caplog.set_level(logging.ERROR)
    transport = ASGITransport(app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=ORIGIN) as client:
        await client.post("/api/session", headers=LOGIN)
        assert (await client.get("/api/messages")).status_code == 500
    [record] = [r for r in caplog.records if "Unhandled error" in r.getMessage()]
    assert record.exc_info is not None
