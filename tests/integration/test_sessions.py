from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from themed_chat.app import create_app
from themed_chat.settings import AppSettings, ModelSettings, SecretSettings, Settings

ORIGIN = "http://127.0.0.1:8000"
ACCESS_KEY = "login_fixture_key"
SIGNING_KEY = "a-long-independent-test-signing-secret"


class Guests:
    def __init__(self) -> None:
        self.created: list[UUID] = []

    async def create(self, guest_id: UUID) -> None:
        self.created.append(guest_id)


@pytest.fixture
def guest_store() -> Guests:
    return Guests()


@pytest.fixture
async def client(guest_store: Guests) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        AppSettings(llm=ModelSettings(model="test", system_prompt="test")),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr(ACCESS_KEY),
            APP_SESSION_SECRET=SecretStr(SIGNING_KEY),
            GEMINI_API_KEY=SecretStr("fixture-key"),
        ),
    )
    app = create_app(settings, guests=guest_store)
    async with AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as client:
        yield client


@pytest.mark.anyio
async def test_valid_key_creates_guest_and_cookie(client: AsyncClient, guest_store: Guests) -> None:
    response = await client.post(
        "/api/session", headers={"Origin": ORIGIN, "X-Access-Key": ACCESS_KEY}
    )
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert ACCESS_KEY not in cookie
    assert len(guest_store.created) == 1
    assert (await client.get("/api/session")).status_code == 204


@pytest.mark.anyio
async def test_incorrect_key_does_not_create_guest(
    client: AsyncClient, guest_store: Guests
) -> None:
    response = await client.post(
        "/api/session", headers={"Origin": ORIGIN, "X-Access-Key": "wrong_key"}
    )
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert not guest_store.created


@pytest.mark.anyio
async def test_origin_must_match_before_login(client: AsyncClient, guest_store: Guests) -> None:
    response = await client.post(
        "/api/session", headers={"Origin": "https://elsewhere.test", "X-Access-Key": ACCESS_KEY}
    )
    assert response.status_code == 403
    assert not guest_store.created


@pytest.mark.anyio
async def test_key_is_not_a_substitute_for_session(client: AsyncClient) -> None:
    response = await client.get("/api/session", headers={"X-Access-Key": ACCESS_KEY})
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_valid_session_reuses_guest(client: AsyncClient, guest_store: Guests) -> None:
    headers = {"Origin": ORIGIN, "X-Access-Key": ACCESS_KEY}
    assert (await client.post("/api/session", headers=headers)).status_code == 204
    assert (await client.post("/api/session", headers=headers)).status_code == 204
    assert len(guest_store.created) == 1


@pytest.mark.anyio
async def test_modified_cookie_is_rejected(client: AsyncClient) -> None:
    headers = {"Origin": ORIGIN, "X-Access-Key": ACCESS_KEY}
    assert (await client.post("/api/session", headers=headers)).status_code == 204
    token = client.cookies["chat_session"]
    client.cookies.clear()
    response = await client.get("/api/session", headers={"Cookie": f"chat_session=x{token}"})
    assert response.status_code == 401
