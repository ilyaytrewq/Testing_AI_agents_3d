import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from socket import AF_INET, SOCK_STREAM, socket

import pytest
import uvicorn
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from support import LOGIN, MemoryStorage, StubGenerator, make_settings

from themed_chat.app import create_app
from themed_chat.settings import AuthSettings

MARKER = "SECRET-QUESTION-MARKER"


def integrity_error() -> IntegrityError:
    detail = f'null value violates constraint. DETAIL: Failing row contains (1, "{MARKER}")'
    return IntegrityError(f"INSERT ... {MARKER}", {"question": MARKER}, Exception(detail))


@asynccontextmanager
async def serve(storage: MemoryStorage) -> AsyncIterator[str]:
    """The app behind a real uvicorn server, as in production."""
    with socket(AF_INET, SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        settings = make_settings(auth=AuthSettings(public_origin=origin))
        app = create_app(settings, storage.overrides(StubGenerator()))
        config = uvicorn.Config(app, log_level="debug", log_config=None, ws="none")
        server = uvicorn.Server(config)
        running = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if running.done():
                        await running
                        raise RuntimeError("Test server failed to start.")
                    await asyncio.sleep(0.01)
            yield origin
        finally:
            server.should_exit = True
            await asyncio.wait_for(running, timeout=10)


@pytest.mark.anyio
async def test_database_error_text_never_reaches_any_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    storage = MemoryStorage()

    async def broken_append(_: object) -> None:
        raise integrity_error()

    storage.append_turn = broken_append  # type: ignore[method-assign,assignment]
    async with serve(storage) as origin, AsyncClient(base_url=origin) as client:
        login = await client.post("/api/session", headers={**LOGIN, "Origin": origin})
        assert login.status_code == 204
        response = await client.post(
            "/api/messages", headers={"Origin": origin}, json={"text": MARKER}
        )
        assert response.status_code == 500
        assert response.json() == {"error": {"code": "internal_error"}}
        assert response.headers["cache-control"] == "no-store"

        async def broken_lookup(*_: object) -> None:
            raise integrity_error()

        # A database bug in the authentication middleware takes the same path.
        storage.active_session = broken_lookup  # type: ignore[method-assign,assignment]
        lookup = await client.get("/api/messages")
        assert lookup.status_code == 500
        assert lookup.json() == {"error": {"code": "internal_error"}}
    messages = [record.getMessage() for record in caplog.records]
    assert any("IntegrityError sqlstate=" in message for message in messages)
    assert MARKER not in caplog.text
    assert all(
        record.exc_info is None for record in caplog.records if "Integrity" in str(record.msg)
    )
    assert not [m for m in messages if "Exception in ASGI application" in m]


@pytest.mark.anyio
async def test_other_errors_are_logged_once_with_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    storage = MemoryStorage()

    async def broken(**_: object) -> int:
        raise RuntimeError("boom")

    storage.latest_revision = broken  # type: ignore[method-assign,assignment]
    async with serve(storage) as origin, AsyncClient(base_url=origin) as client:
        await client.post("/api/session", headers={**LOGIN, "Origin": origin})
        response = await client.get("/api/messages")
        assert response.status_code == 500
    records = [r for r in caplog.records if r.exc_info is not None]
    assert len(records) == 1 and "Unhandled error" in records[0].getMessage()


@pytest.mark.anyio
async def test_error_after_a_complete_response_is_only_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from themed_chat.api.internal_errors import InternalErrorMiddleware

    async def finishes_then_fails(_scope: object, _receive: object, send: object) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b"done", "more_body": False})  # type: ignore[operator]
        raise RuntimeError("after the response")

    async def fails_midway(_scope: object, _receive: object, send: object) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b"part", "more_body": True})  # type: ignore[operator]
        raise RuntimeError("in the middle")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "GET", "path": "/api/x", "headers": []}
    for app, expected in (
        (finishes_then_fails, ["http.response.start", "http.response.body"]),
        (fails_midway, ["http.response.start", "http.response.body", "http.response.body"]),
    ):
        sent: list[dict[str, object]] = []

        async def send(message: dict[str, object], sent: list[dict[str, object]] = sent) -> None:
            sent.append(message)

        await InternalErrorMiddleware(app)(scope, receive, send)  # type: ignore[arg-type]
        assert [m["type"] for m in sent] == expected
        assert sent[-1].get("more_body", False) is False
    assert caplog.text.count("Unhandled error on GET /api/x") == 2
