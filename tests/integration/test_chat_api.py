import json
from datetime import datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from pydantic import SecretStr

from themed_chat.app import create_app
from themed_chat.chat.models import DraftTurn, Turn
from themed_chat.settings import AppSettings, ModelSettings, SecretSettings, Settings

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"Origin": ORIGIN, "X-Access-Key": "chat_test_key"}


class Guests:
    async def create(self, guest_id: UUID) -> None:
        pass


class Generator:
    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.reply = "Start with 18 grams."

    async def generate(self, text: str) -> str:
        self.inputs.append(text)
        return self.reply


class Repository:
    def __init__(self) -> None:
        self.turns: list[Turn] = []

    async def list_turns(self) -> list[Turn]:
        return list(self.turns)

    async def append_turn(self, draft: DraftTurn) -> Turn:
        turn = Turn(len(self.turns) + 1, draft)
        self.turns.append(turn)
        return turn


@pytest.mark.anyio
async def test_authorized_guest_can_send_and_read_shared_history() -> None:
    settings = Settings(
        AppSettings(llm=ModelSettings(model="fixture", system_prompt="fixture")),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr("chat_test_key"),
            APP_SESSION_SECRET=SecretStr("chat-test-signing-secret-long-enough"),
            GEMINI_API_KEY=SecretStr("unused-provider-key"),
            DATABASE_URL=SecretStr("postgresql+asyncpg://unused.test/chat"),
        ),
    )
    generator = Generator()
    app = create_app(settings, guests=Guests(), repository=Repository(), generator=generator)
    async with (
        AsyncClient(
            transport=ASGITransport(app, raise_app_exceptions=False), base_url=ORIGIN
        ) as alice,
        AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as bob,
    ):
        assert (await alice.get("/api/messages")).status_code == 401
        assert (await alice.post("/api/session", headers=HEADERS)).status_code == 204
        invalid = await alice.post("/api/messages", headers=HEADERS, json={"text": "   "})
        assert invalid.status_code == 422
        for malformed in (b'{"text":"\\ud800"}', b'{"text":1e400}', b'{"text":"x","user_id":"y"}'):
            response = await alice.post(
                "/api/messages",
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
                content=malformed,
            )
            assert response.status_code == 422
            assert response.json() == {"error": {"code": "invalid_request"}}
        assert not generator.inputs
        generator.reply = "\ud800"
        rejected = await alice.post(
            "/api/messages", headers=HEADERS, json={"text": "Rejected answer"}
        )
        assert rejected.status_code == 502
        empty_history = await alice.get("/api/messages")
        assert empty_history.status_code == 200 and empty_history.json()["messages"] == []
        generator.reply = "Start with 18 grams."
        sent = await alice.post("/api/messages", headers=HEADERS, json={"text": "Espresso ratio?"})
        assert sent.status_code == 201
        assert sent.json()["messages"][0]["is_mine"] is True
        assert (await bob.post("/api/session", headers=HEADERS)).status_code == 204
        history = await bob.get("/api/messages")
        assert history.status_code == 200
        messages = history.json()["messages"]
        assert [m["text"] for m in messages] == ["Espresso ratio?", "Start with 18 grams."]
        assert messages[0]["is_mine"] is False
        assert datetime.fromisoformat(messages[0]["created_at"]).utcoffset() is not None
    assert generator.inputs == ["Rejected answer", "Espresso ratio?"]


def test_custom_guest_store_requires_matching_chat_store() -> None:
    with pytest.raises(ValueError, match="guest and chat repositories together"):
        create_app(guests=Guests(), generator=Generator())


@pytest.mark.anyio
async def test_app_selects_openai_compatible_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(request: Request) -> Response:
        assert str(request.url) == "https://qwen.test/compatible-mode/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer qwen-fixture"
        assert json.loads(request.content)["model"] == "qwen-plus"
        return Response(200, json={"choices": [{"message": {"content": "Use a filter."}}]})

    http = AsyncClient(transport=MockTransport(respond))
    monkeypatch.setattr("themed_chat.adapters.openai_compatible.AsyncClient", lambda **_: http)
    settings = Settings(
        AppSettings(
            llm=ModelSettings(
                provider="openai_compatible",
                base_url="https://qwen.test/compatible-mode/v1",
                model="qwen-plus",
                system_prompt="Coffee only",
            )
        ),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr("chat_test_key"),
            APP_SESSION_SECRET=SecretStr("chat-test-signing-secret-long-enough"),
            OPENAI_COMPATIBLE_API_KEY=SecretStr("qwen-fixture"),
            DATABASE_URL=SecretStr("postgresql+asyncpg://unused.test/chat"),
        ),
    )
    app = create_app(settings, guests=Guests(), repository=Repository())
    try:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app), base_url=ORIGIN) as client,
        ):
            assert (await client.post("/api/session", headers=HEADERS)).status_code == 204
            reply = await client.post(
                "/api/messages", headers=HEADERS, json={"text": "How to brew?"}
            )
            assert reply.status_code == 201
            history = await client.get("/api/messages")
            assert [item["text"] for item in history.json()["messages"]] == [
                "How to brew?",
                "Use a filter.",
            ]
        assert http.is_closed
    finally:
        await http.aclose()
