import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from themed_chat.app import create_app
from themed_chat.chat.service import GenerationTimeout
from themed_chat.settings import (
    AppSettings,
    ModelSettings,
    SecretSettings,
    Settings,
)

ORIGIN = "http://127.0.0.1:8000"
LOGIN = {"Origin": ORIGIN, "X-Access-Key": "history_test_key"}


class FixtureGenerator:
    async def generate(self, text: str) -> str:
        if text == "simulate timeout":
            raise GenerationTimeout("Test provider timeout.")
        return f"Reply: {text}"


@pytest.mark.anyio
async def test_history_is_atomic_shared_and_persistent(postgres_dsn: SecretStr) -> None:
    settings = Settings(
        AppSettings(llm=ModelSettings(model="fixture", system_prompt="fixture")),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr("history_test_key"),
            APP_SESSION_SECRET=SecretStr("session-secret-for-the-persistence-fixture"),
            GEMINI_API_KEY=SecretStr("unused-provider-key"),
            DATABASE_URL=postgres_dsn,
        ),
    )
    app = create_app(settings, generator=FixtureGenerator())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as alice,
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as bob,
    ):
        assert (await alice.post("/api/session", headers=LOGIN)).status_code == 204
        assert (await bob.post("/api/session", headers=LOGIN)).status_code == 204
        responses = await asyncio.gather(
            alice.post("/api/messages", headers={"Origin": ORIGIN}, json={"text": "first"}),
            bob.post("/api/messages", headers={"Origin": ORIGIN}, json={"text": "second"}),
        )
        assert [r.status_code for r in responses] == [201, 201]
        history = (await alice.get("/api/messages")).json()["messages"]
        other = (await bob.get("/api/messages")).json()["messages"]
        assert [m["id"] for m in history] == [m["id"] for m in other]
        failed = await alice.post(
            "/api/messages", headers={"Origin": ORIGIN}, json={"text": "simulate timeout"}
        )
        assert failed.status_code == 504
        assert len(history) == 4
        assert sum(m["is_mine"] for m in history) == 1
        assert all(m["created_at"].endswith("Z") for m in history)
        assert history[1]["text"] == f"Reply: {history[0]['text']}"
        assert history[3]["text"] == f"Reply: {history[2]['text']}"
        cookies = alice.cookies

    restarted = create_app(settings, generator=FixtureGenerator())
    async with (
        restarted.router.lifespan_context(restarted),
        AsyncClient(transport=ASGITransport(restarted), base_url=ORIGIN, cookies=cookies) as client,
    ):
        assert (await client.get("/api/messages")).json()["messages"] == history
