from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

MAX_MESSAGE_LENGTH = 500
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

TurnStatus = Literal["answered", "failed"]


class TruncatedText(str):
    """Model text that the provider cut off at its token limit.

    A str subclass, so TextGenerator.generate still returns plain text to every caller
    and test double; ChatService checks the type to mark the answer as cut.
    """

    __slots__ = ()


# Appended to a cut answer, by question language (the languages of guard.refusals);
# any other language gets English.
TRUNCATION_MARKERS = {
    "ru": "…(ответ обрезан)",
    "en": "…(answer truncated)",
    "de": "…(Antwort abgeschnitten)",
    "uk": "…(відповідь обрізано)",
    "zh": "…（回答被截断）",
    "es": "…(respuesta truncada)",
    "fr": "…(réponse tronquée)",
}


@dataclass(frozen=True, slots=True)
class NewTurn:
    """A question and its outcome that are not stored yet; a failed turn has no answer."""

    user_id: UUID
    question: str
    answer: str | None
    question_at: datetime
    answer_at: datetime
    status: TurnStatus = "answered"


@dataclass(frozen=True, slots=True)
class Turn:
    """A stored turn. Display order is (question_at, id); `revision` orders the writes."""

    id: int
    user_id: UUID
    question: str
    answer: str | None
    question_at: datetime
    answer_at: datetime
    status: TurnStatus
    revision: int


@dataclass(frozen=True, slots=True)
class HistoryPage:
    """Turns in display order; `revision` is the cursor for the next change poll."""

    turns: list[Turn]
    has_more: bool
    revision: int


@dataclass(frozen=True, slots=True)
class GuestSession:
    """A server-side login; the cookie only carries its id."""

    id: UUID
    guest_id: UUID
    key_fingerprint: str
    created_at: datetime
    expires_at: datetime
