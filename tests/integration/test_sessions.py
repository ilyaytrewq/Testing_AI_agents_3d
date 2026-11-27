from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from support import (
    ACCESS_KEY,
    LOGIN,
    ORIGIN,
    WRITE,
    MemoryStorage,
    StubGenerator,
    client_for,
    make_settings,
)

from themed_chat.app import create_app
from themed_chat.settings import AuthSettings


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
async def client(storage: MemoryStorage) -> AsyncIterator[AsyncClient]:
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app) as client:
        yield client


@pytest.mark.anyio
async def test_valid_key_creates_guest_and_cookies(
    client: AsyncClient, storage: MemoryStorage
) -> None:
    response = await client.post("/api/session", headers=LOGIN)
    assert response.status_code == 204
    cookies = [value.lower() for value in response.headers.get_list("set-cookie")]
    assert len(cookies) == 2
    for cookie in cookies:
        assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api" in cookie
        assert ACCESS_KEY not in cookie
    assert len(storage.guests) == 1
    assert (await client.get("/api/messages")).status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("key", ["wrong_key_value", "short", "bad key!", "x" * 300, ""])
async def test_incorrect_key_does_not_create_guest(
    client: AsyncClient, storage: MemoryStorage, key: str
) -> None:
    response = await client.post("/api/session", headers={"Origin": ORIGIN, "X-Access-Key": key})
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthorized"}}
    assert "set-cookie" not in response.headers
    assert not storage.guests


@pytest.mark.anyio
async def test_origin_must_match_before_login(client: AsyncClient, storage: MemoryStorage) -> None:
    for origin in ("https://elsewhere.test", "http://127.0.0.1:9999", "http://evil.localhost"):
        response = await client.post(
            "/api/session", headers={"Origin": origin, "X-Access-Key": ACCESS_KEY}
        )
        assert response.status_code == 403
        assert response.json() == {"error": {"code": "origin_not_allowed"}}
    missing = await client.post("/api/session", headers={"X-Access-Key": ACCESS_KEY})
    assert missing.status_code == 403
    assert not storage.guests


@pytest.mark.anyio
@pytest.mark.parametrize(
    "origin",
    ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"],
)
async def test_loopback_origins_are_equivalent(storage: MemoryStorage, origin: str) -> None:
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app, origin) as client:
        response = await client.post(
            "/api/session", headers={"Origin": origin, "X-Access-Key": ACCESS_KEY}
        )
    assert response.status_code == 204


@pytest.mark.anyio
@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:8000",
        "http://localhost:8001",
        "http://localhost",
        "http://localhost.evil.test:8000",
    ],
)
async def test_loopback_equivalence_keeps_scheme_and_port(
    storage: MemoryStorage, origin: str
) -> None:
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app) as client:
        response = await client.post(
            "/api/session", headers={"Origin": origin, "X-Access-Key": ACCESS_KEY}
        )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_public_origin_must_match_exactly(storage: MemoryStorage) -> None:
    settings = make_settings(auth=AuthSettings(public_origin="https://chat.example.com"))
    app = create_app(settings, storage.overrides(StubGenerator()))
    async with client_for(app, "https://chat.example.com") as client:
        for origin, expected in (
            ("https://chat.example.com", 204),
            ("http://chat.example.com", 403),
            ("https://chat.example.com:8443", 403),
            ("https://other.example.com", 403),
            ("http://localhost:443", 403),
            ("https://localhost", 403),
        ):
            response = await client.post(
                "/api/session", headers={"Origin": origin, "X-Access-Key": ACCESS_KEY}
            )
            assert response.status_code == expected, origin


@pytest.mark.anyio
async def test_key_is_not_a_substitute_for_session(client: AsyncClient) -> None:
    response = await client.get("/api/messages", headers={"X-Access-Key": ACCESS_KEY})
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert (await client.get("/api/session")).status_code == 401


@pytest.mark.anyio
async def test_valid_session_reuses_guest(client: AsyncClient, storage: MemoryStorage) -> None:
    assert (await client.post("/api/session", headers=LOGIN)).status_code == 204
    assert (await client.post("/api/session", headers=LOGIN)).status_code == 204
    assert len(storage.guests) == 1


@pytest.mark.anyio
async def test_get_session_endpoint_is_gone(client: AsyncClient) -> None:
    await client.post("/api/session", headers=LOGIN)
    response = await client.get("/api/session")
    assert response.status_code == 405
    assert response.json() == {"error": {"code": "method_not_allowed"}}


@pytest.mark.anyio
async def test_modified_cookie_is_rejected(client: AsyncClient) -> None:
    assert (await client.post("/api/session", headers=LOGIN)).status_code == 204
    token = client.cookies["chat_session"]
    client.cookies.clear()
    response = await client.get("/api/messages", headers={"Cookie": f"chat_session=x{token}"})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_logout_ends_the_session_and_needs_an_origin(client: AsyncClient) -> None:
    await client.post("/api/session", headers=LOGIN)
    assert (await client.delete("/api/session")).status_code == 403
    assert (await client.get("/api/messages")).status_code == 200
    response = await client.delete("/api/session", headers=WRITE)
    assert response.status_code == 204
    assert (await client.get("/api/messages")).status_code == 401
    # Logging out twice is harmless.
    assert (await client.delete("/api/session", headers=WRITE)).status_code == 204


@pytest.mark.anyio
async def test_session_dies_when_the_access_key_changes(storage: MemoryStorage) -> None:
    old = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(old) as client:
        await client.post("/api/session", headers=LOGIN)
        assert (await client.get("/api/messages")).status_code == 200
        cookies = client.cookies

    rotated = create_app(
        make_settings(access_key="rotated_access_key"), storage.overrides(StubGenerator())
    )
    async with client_for(rotated) as client:
        client.cookies.update(cookies)
        response = await client.get("/api/messages")
        assert response.status_code == 401
        # The same person can come back with the new key.
        headers = {"Origin": ORIGIN, "X-Access-Key": "rotated_access_key"}
        assert (await client.post("/api/session", headers=headers)).status_code == 204
        assert (await client.get("/api/messages")).status_code == 200


@pytest.mark.anyio
async def test_relogin_keeps_the_same_guest(client: AsyncClient, storage: MemoryStorage) -> None:
    await client.post("/api/session", headers=LOGIN)
    sent = await client.post("/api/messages", headers=WRITE, json={"text": "Hello"})
    assert sent.json()["messages"][0]["is_mine"] is True
    await client.delete("/api/session", headers=WRITE)
    await client.post("/api/session", headers=LOGIN)
    history = (await client.get("/api/messages")).json()["messages"]
    assert [m["is_mine"] for m in history] == [True, False]
    assert len(storage.guests) == 1


@pytest.mark.anyio
async def test_unknown_or_forged_guest_cookie_gets_a_new_guest(
    client: AsyncClient, storage: MemoryStorage
) -> None:
    await client.post("/api/session", headers=LOGIN)
    token = client.cookies["chat_guest"]
    await client.delete("/api/session", headers=WRITE)

    client.cookies.set("chat_guest", f"x{token}", path="/api")
    await client.post("/api/session", headers=LOGIN)
    assert len(storage.guests) == 2

    # A valid signature for a guest that is not in the database is not trusted either.
    storage.guests.clear()
    await client.delete("/api/session", headers=WRITE)
    client.cookies.set("chat_guest", token, path="/api")
    await client.post("/api/session", headers=LOGIN)
    assert len(storage.guests) == 1


@pytest.mark.anyio
async def test_guest_cookie_is_not_authorization(client: AsyncClient) -> None:
    await client.post("/api/session", headers=LOGIN)
    await client.delete("/api/session", headers=WRITE)
    assert client.cookies["chat_guest"]
    assert (await client.get("/api/messages")).status_code == 401


@pytest.mark.anyio
async def test_login_attempts_are_rate_limited(storage: MemoryStorage) -> None:
    settings = make_settings(auth=AuthSettings(login_attempts=3, login_window_seconds=60))
    app = create_app(settings, storage.overrides(StubGenerator()))
    wrong = {"Origin": ORIGIN, "X-Access-Key": "wrong_key_value"}
    async with client_for(app) as client:
        for _ in range(3):
            assert (await client.post("/api/session", headers=wrong)).status_code == 401
        blocked = await client.post("/api/session", headers=wrong)
        assert blocked.status_code == 429
        assert blocked.json() == {"error": {"code": "too_many_requests"}}
        assert 1 <= int(blocked.headers["retry-after"]) <= 60
        # Even the correct key waits: otherwise guessing could not be slowed down.
        assert (await client.post("/api/session", headers=LOGIN)).status_code == 429
        assert not storage.guests


@pytest.mark.anyio
async def test_cookies_are_secure_behind_https(storage: MemoryStorage) -> None:
    origin = "https://chat.example.com"
    app = create_app(
        make_settings(auth=AuthSettings(public_origin=origin)), storage.overrides(StubGenerator())
    )
    async with client_for(app, origin) as client:
        response = await client.post(
            "/api/session", headers={"Origin": origin, "X-Access-Key": ACCESS_KEY}
        )
    cookies = [value.lower() for value in response.headers.get_list("set-cookie")]
    assert len(cookies) == 2 and all("secure" in cookie for cookie in cookies)


@pytest.mark.anyio
async def test_copied_cookie_stops_working_after_logout(
    client: AsyncClient, storage: MemoryStorage
) -> None:
    assert (await client.post("/api/session", headers=LOGIN)).status_code == 204
    stolen = client.cookies.get("chat_session")
    assert stolen is not None and len(storage.sessions) == 1
    assert (await client.delete("/api/session", headers=WRITE)).status_code == 204
    client.cookies.set("chat_session", stolen, domain="127.0.0.1", path="/api")
    replay = await client.get("/api/messages")
    assert replay.status_code == 401
    assert replay.json() == {"error": {"code": "unauthorized"}}


@pytest.mark.anyio
async def test_cookie_only_carries_the_session_id(storage: MemoryStorage) -> None:
    from base64 import b64decode
    from json import loads

    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app) as client:
        await client.post("/api/session", headers=LOGIN)
        payload = client.cookies["chat_session"].split(".")[0]
        data = loads(b64decode(payload + "=" * (-len(payload) % 4)))
    [session_id] = storage.sessions
    assert data == {"sid": str(session_id)}


@pytest.mark.anyio
async def test_deleted_guest_invalidates_the_session(
    client: AsyncClient, storage: MemoryStorage
) -> None:
    await client.post("/api/session", headers=LOGIN)
    assert (await client.get("/api/messages")).status_code == 200
    storage.delete_guest(storage.guests[0])
    assert (await client.get("/api/messages")).status_code == 401


@pytest.mark.anyio
async def test_expired_session_is_rejected_and_pruned(storage: MemoryStorage) -> None:
    from datetime import UTC, datetime, timedelta

    from themed_chat.chat.models import GuestSession

    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app) as client:
        await client.post("/api/session", headers=LOGIN)
        [session_id] = storage.sessions
        old = storage.sessions[session_id]
        past = datetime.now(UTC) - timedelta(seconds=5)
        storage.sessions[session_id] = GuestSession(
            old.id, old.guest_id, old.key_fingerprint, past - timedelta(hours=1), past
        )
        assert (await client.get("/api/messages")).status_code == 401
        await client.post("/api/session", headers=LOGIN)
    assert session_id not in storage.sessions and len(storage.sessions) == 1


@pytest.mark.anyio
async def test_relogin_replaces_the_previous_session(
    client: AsyncClient, storage: MemoryStorage
) -> None:
    await client.post("/api/session", headers=LOGIN)
    first = client.cookies["chat_session"]
    await client.post("/api/session", headers=LOGIN)
    assert len(storage.revoked) == 1
    client.cookies.set("chat_session", first, domain="127.0.0.1", path="/api")
    assert (await client.get("/api/messages")).status_code == 401


@pytest.mark.anyio
async def test_login_limit_uses_the_client_behind_a_trusted_proxy(storage: MemoryStorage) -> None:
    from httpx import ASGITransport

    settings = make_settings(auth=AuthSettings(login_attempts=1, trusted_proxies=["127.0.0.0/8"]))
    app = create_app(settings, storage.overrides(StubGenerator()))
    transport = ASGITransport(app, client=("127.0.0.1", 5000))
    bad = {"Origin": ORIGIN, "X-Access-Key": "wrong_key_123"}
    async with AsyncClient(transport=transport, base_url=ORIGIN) as client:
        first = {**bad, "X-Forwarded-For": "198.51.100.1"}
        assert (await client.post("/api/session", headers=first)).status_code == 401
        assert (await client.post("/api/session", headers=first)).status_code == 429
        # Another client behind the same proxy has its own allowance.
        other = {**bad, "X-Forwarded-For": "198.51.100.2"}
        assert (await client.post("/api/session", headers=other)).status_code == 401


@pytest.mark.anyio
async def test_spoofed_forwarded_for_from_an_untrusted_peer_is_ignored(
    storage: MemoryStorage,
) -> None:
    from httpx import ASGITransport

    settings = make_settings(auth=AuthSettings(login_attempts=1, trusted_proxies=["10.0.0.0/8"]))
    app = create_app(settings, storage.overrides(StubGenerator()))
    transport = ASGITransport(app, client=("203.0.113.9", 5000))
    async with AsyncClient(transport=transport, base_url=ORIGIN) as client:
        for spoof, status in (("198.51.100.1", 401), ("198.51.100.2", 429)):
            headers = {"Origin": ORIGIN, "X-Access-Key": "wrong_key_123", "X-Forwarded-For": spoof}
            assert (await client.post("/api/session", headers=headers)).status_code == status
