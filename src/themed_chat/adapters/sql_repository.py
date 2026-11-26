from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from themed_chat.chat.models import DraftTurn, Turn


class Base(DeclarativeBase):
    pass


class GuestRow(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SqlGuestRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create(self, guest_id: UUID) -> None:
        async with self.sessions.begin() as session:
            session.add(GuestRow(id=guest_id, created_at=datetime.now(UTC)))


class ChatTurnRow(Base):
    __tablename__ = "chat_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("users.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    question_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answer_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqlChatRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def list_turns(self) -> list[Turn]:
        async with self.sessions() as session:
            rows = await session.scalars(select(ChatTurnRow).order_by(ChatTurnRow.id))
            return [
                Turn(
                    row.id,
                    DraftTurn(
                        row.user_id,
                        row.question,
                        row.answer,
                        _utc(row.question_at),
                        _utc(row.answer_at),
                    ),
                )
                for row in rows
            ]

    async def append_turn(self, draft: DraftTurn) -> Turn:
        async with self.sessions.begin() as session:
            row = ChatTurnRow(
                user_id=draft.user_id,
                question=draft.question,
                answer=draft.answer,
                question_at=_utc(draft.question_at),
                answer_at=_utc(draft.answer_at),
            )
            session.add(row)
            await session.flush()
            turn_id = row.id
        return Turn(turn_id, draft)
