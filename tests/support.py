"""Shared test doubles: in-memory storage, a stub model and settings builders."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from themed_chat.app import Overrides, Storage
from themed_chat.chat.models import GuestSession, NewTurn, Turn
from themed_chat.settings import (
    AppSettings,
    AuthSettings,
    ChatSettings,
    ModelSettings,
    SecretSettings,
    Settings,
)

ORIGIN = "http://127.0.0.1:8000"
ACCESS_KEY = "support_access_key"
SESSION_SECRET = "support-session-secret-0123456789abcdef"
LOGIN = {"Origin": ORIGIN, "X-Access-Key": ACCESS_KEY}
WRITE = {"Origin": ORIGIN}
UNUSED_DATABASE = "postgresql+asyncpg://unused.test/chat"


def make_settings(
    *,
    access_key: str = ACCESS_KEY,
    session_secret: str = SESSION_SECRET,
    database_url: str = UNUSED_DATABASE,
    auth: AuthSettings | None = None,
    chat: ChatSettings | None = None,
    llm: ModelSettings | None = None,
) -> Settings:
    return Settings(
        AppSettings(
            auth=auth or AuthSettings(),
            chat=chat or ChatSettings(),
            llm=llm
            or ModelSettings(
                base_url="https://unused.test/v1", model="fixture", system_prompt="fixture"
            ),
        ),
        SecretSettings(
            APP_ACCESS_KEY=SecretStr(access_key),
            APP_SESSION_SECRET=SecretStr(session_secret),
            LLM_API_KEY=SecretStr("unused-provider-key"),
            DATABASE_URL=SecretStr(database_url),
        ),
    )


class StubGenerator:
    def __init__(self, reply: str = "Start with 18 grams.") -> None:
        self.reply = reply
        self.error: Exception | None = None
        self.inputs: list[str] = []

    async def generate(self, text: str) -> str:
        self.inputs.append(text)
        if self.error is not None:
            raise self.error
        return self.reply


class MemoryStorage:
    """Guests, sessions and chat turns in memory, with the SQL repository's ordering rules."""

    def __init__(self) -> None:
        self.guests: list[UUID] = []
        self.turns: list[Turn] = []
        self.sessions: dict[UUID, GuestSession] = {}
        self.revoked: set[UUID] = set()
        self.healthy = True

    async def create(self, guest_id: UUID) -> None:
        self.guests.append(guest_id)

    async def exists(self, guest_id: UUID) -> bool:
        return guest_id in self.guests

    def delete_guest(self, guest_id: UUID) -> None:
        """Like the SQL foreign key: the guest's sessions go with it."""
        self.guests.remove(guest_id)
        for key in [key for key, value in self.sessions.items() if value.guest_id == guest_id]:
            del self.sessions[key]

    async def create_session(self, session: GuestSession) -> None:
        for key in [k for k, v in self.sessions.items() if v.expires_at < session.created_at]:
            del self.sessions[key]
        self.sessions[session.id] = session

    async def active_session(
        self, session_id: UUID, key_fingerprint: str, now: datetime
    ) -> GuestSession | None:
        session = self.sessions.get(session_id)
        if (
            session is None
            or session_id in self.revoked
            or session.key_fingerprint != key_fingerprint
            or session.expires_at <= now
        ):
            return None
        return session

    async def revoke_session(self, session_id: UUID, now: datetime) -> None:
        if session_id in self.sessions:
            self.revoked.add(session_id)

    def _ordered(self) -> list[Turn]:
        return sorted(self.turns, key=lambda turn: (turn.question_at, turn.id))

    async def list_turns(self, *, limit: int, before: int | None = None) -> list[Turn]:
        ordered = self._ordered()
        if before is not None:
            anchor = next((turn for turn in self.turns if turn.id == before), None)
            if anchor is None:
                return []
            key = (anchor.question_at, anchor.id)
            ordered = [turn for turn in ordered if (turn.question_at, turn.id) < key]
        return ordered[-limit:]

    async def list_changes(self, *, after_revision: int, limit: int) -> list[Turn]:
        changed = sorted(
            (turn for turn in self.turns if turn.revision > after_revision),
            key=lambda turn: turn.revision,
        )
        return changed[:limit]

    async def latest_revision(self) -> int:
        return max((turn.revision for turn in self.turns), default=0)

    async def append_turn(self, turn: NewTurn) -> Turn:
        saved = Turn(
            len(self.turns) + 1,
            turn.user_id,
            turn.question,
            turn.answer,
            turn.question_at,
            turn.answer_at,
            turn.status,
            await self.latest_revision() + 1,
        )
        self.turns.append(saved)
        return saved

    async def ping(self) -> None:
        if not self.healthy:
            raise ConnectionError("storage is down")

    def add_turns(self, count: int, user_id: UUID) -> None:
        start = datetime.now(UTC)
        for number in range(1, count + 1):
            at = start + timedelta(seconds=number)
            self.turns.append(
                Turn(
                    len(self.turns) + 1,
                    user_id,
                    f"q{number}",
                    f"a{number}",
                    at,
                    at,
                    "answered",
                    len(self.turns) + 1,
                )
            )

    def overrides(self, generator: StubGenerator | None = None) -> Overrides:
        return Overrides(Storage(self, self, self), generator)


def client_for(app: object, base_url: str = ORIGIN) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app), base_url=base_url)  # type: ignore[arg-type]
