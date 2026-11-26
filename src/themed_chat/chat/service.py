from datetime import UTC, datetime
from uuid import UUID

from themed_chat.chat.models import MAX_MESSAGE_LENGTH, DraftTurn, Turn
from themed_chat.chat.ports import ChatRepository, TextGenerator


class InvalidMessage(ValueError):
    """The input is outside the chat's input contract."""


class GenerationError(RuntimeError):
    """The model did not produce a usable response."""


class GenerationTimeout(GenerationError):
    """The model took too long to respond."""


class ChatService:
    def __init__(self, repository: ChatRepository, generator: TextGenerator) -> None:
        self.repository = repository
        self.generator = generator

    async def history(self) -> list[Turn]:
        return await self.repository.list_turns()

    async def send(self, user_id: UUID, text: str) -> Turn:
        if not text.strip() or len(text) > MAX_MESSAGE_LENGTH:
            raise InvalidMessage("Use between 1 and 500 characters, excluding blank messages.")
        question_at = datetime.now(UTC)
        answer = await self.generator.generate(text)
        if not answer.strip():
            raise GenerationError("The model returned an empty answer.")
        draft = DraftTurn(user_id, text, answer, question_at, datetime.now(UTC))
        return await self.repository.append_turn(draft)
