from typing import Protocol
from uuid import UUID

from themed_chat.chat.models import DraftTurn, Turn


class ChatRepository(Protocol):
    async def list_turns(self) -> list[Turn]: ...

    async def append_turn(self, draft: DraftTurn) -> Turn: ...


class TextGenerator(Protocol):
    async def generate(self, text: str) -> str: ...


class GuestRepository(Protocol):
    async def create(self, guest_id: UUID) -> None: ...
