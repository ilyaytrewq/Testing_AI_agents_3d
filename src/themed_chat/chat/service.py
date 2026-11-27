import logging
from datetime import UTC, datetime
from uuid import UUID

from themed_chat.chat.errors import GenerationError, GenerationTimeout
from themed_chat.chat.guard import TopicGuard
from themed_chat.chat.models import (
    MAX_MESSAGE_LENGTH,
    TRUNCATION_MARKERS,
    HistoryPage,
    NewTurn,
    TruncatedText,
    Turn,
)
from themed_chat.chat.ports import ChatRepository, TextGenerator
from themed_chat.log_safety import log_exception

logger = logging.getLogger(__name__)

__all__ = ["ChatService", "GenerationError", "GenerationTimeout", "InvalidMessage"]


class InvalidMessage(ValueError):
    """The input is outside the chat's input contract."""


def _usable_text(text: str) -> bool:
    if not text.strip() or "\x00" in text:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _close_open_fence(text: str) -> str:
    """Close a ``` block left open by the cut, so the marker is not shown as code."""
    fences = sum(1 for line in text.splitlines() if line.lstrip().startswith("```"))
    return f"{text}\n```" if fences % 2 else text


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        generator: TextGenerator,
        guard: TopicGuard | None = None,
    ) -> None:
        self.repository = repository
        self.generator = generator
        self.guard = guard

    async def history(self, *, limit: int, before: int | None = None) -> HistoryPage:
        # The cursor is read first: turns written meanwhile come again with the next poll.
        revision = await self.repository.latest_revision()
        # One extra row tells whether another page exists without a second query.
        turns = await self.repository.list_turns(limit=limit + 1, before=before)
        return HistoryPage(turns[-limit:], len(turns) > limit, revision)

    async def changes(self, *, after_revision: int, limit: int) -> HistoryPage:
        turns = await self.repository.list_changes(after_revision=after_revision, limit=limit + 1)
        kept = turns[:limit]
        revision = kept[-1].revision if kept else after_revision
        return HistoryPage(kept, len(turns) > limit, revision)

    async def send(self, user_id: UUID, text: str) -> Turn:
        if len(text) > MAX_MESSAGE_LENGTH or not _usable_text(text):
            raise InvalidMessage("Use between 1 and 500 characters, excluding blank messages.")
        question_at = datetime.now(UTC)
        try:
            answer = await self._answer(text)
        except GenerationError:
            # The question stays in the history as unanswered; the caller still gets the error.
            failed = NewTurn(user_id, text, None, question_at, datetime.now(UTC), "failed")
            try:
                await self.repository.append_turn(failed)
            except Exception as save_error:
                # The client still gets 502/504 for the model failure, not a 500.
                log_exception(logger, "The failed question could not be saved: %s", save_error)
            raise
        turn = NewTurn(user_id, text, answer, question_at, datetime.now(UTC))
        return await self.repository.append_turn(turn)

    async def _answer(self, text: str) -> str:
        language = None
        if self.guard is not None:
            verdict = await self.guard.check_question(text)
            if not verdict.on_topic:
                # A refusal is a normal answer; the main model is not called.
                return self.guard.policy.refusal(verdict.language)
            language = verdict.language
        answer = await self.generator.generate(text)
        if not _usable_text(answer):
            logger.warning("The model returned unusable text.")
            raise GenerationError("The model returned unusable text.")
        reviewed = answer
        if self.guard is not None and language is not None:
            reviewed = await self.guard.review_answer(answer, language)
        if isinstance(answer, TruncatedText) and reviewed is answer:
            # Saved anyway, but the reader sees that it stops early.
            fallback = self.guard.policy.default_language if self.guard is not None else "ru"
            marker_language = language or fallback
            marker = TRUNCATION_MARKERS.get(marker_language, TRUNCATION_MARKERS["en"])
            return f"{_close_open_fence(answer)}\n\n{marker}"
        return reviewed
