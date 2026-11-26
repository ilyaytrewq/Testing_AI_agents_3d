from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

MAX_MESSAGE_LENGTH = 500


@dataclass(frozen=True, slots=True)
class DraftTurn:
    user_id: UUID
    question: str
    answer: str
    question_at: datetime
    answer_at: datetime


@dataclass(frozen=True, slots=True)
class Turn:
    id: int
    draft: DraftTurn
