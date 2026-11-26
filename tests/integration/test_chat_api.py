from datetime import datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
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
