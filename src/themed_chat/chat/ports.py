from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from themed_chat.chat.models import GuestSession, NewTurn, Turn


class ChatRepository(Protocol):
    async def list_turns(self, *, limit: int, before: int | None = None) -> list[Turn]:
        """Return at most `limit` turns in display order, (question_at, id) ascending.

        These are the latest turns, or, with `before`, the latest ones that come before
        that turn in display order.
        """
        ...

    async def list_changes(self, *, after_revision: int, limit: int) -> list[Turn]:
        """Return at most `limit` turns written after `after_revision`, by revision.

        Writes commit in revision order, so polling with the largest seen revision
        never skips a turn.
        """
        ...

    async def latest_revision(self) -> int:
        """The largest committed revision, or 0 for an empty history."""
        ...

    async def append_turn(self, turn: NewTurn) -> Turn: ...

    async def ping(self) -> None:
        """Raise if the storage is not reachable."""
        ...


class TextGenerator(Protocol):
    async def generate(self, text: str) -> str:
        """Return text or raise GenerationError (GenerationTimeout for a deadline)."""
        ...


class Completion(Protocol):
    async def complete(
        self,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
        *,
        response_format: Mapping[str, object] | None = None,
    ) -> str:
        """Return the model's text or raise GenerationError.

        GenerationTimeout for a deadline; EmptyCompletion when the provider answered with no
        text. `response_format` is the OpenAI-style structured output request, if any.
        """
        ...


class ModelClient(TextGenerator, Completion, Protocol):
    """What a model provider adapter offers: a chat answer and a raw completion."""


class GuestRepository(Protocol):
    async def create(self, guest_id: UUID) -> None: ...

    async def exists(self, guest_id: UUID) -> bool: ...


class SessionRepository(Protocol):
    async def create_session(self, session: GuestSession) -> None:
        """Store a new session; may also delete expired ones."""
        ...

    async def active_session(
        self, session_id: UUID, key_fingerprint: str, now: datetime
    ) -> GuestSession | None:
        """Return the session if it exists, is not revoked or expired, and has this key."""
        ...

    async def revoke_session(self, session_id: UUID, now: datetime) -> None: ...
