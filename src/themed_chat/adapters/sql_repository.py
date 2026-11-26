from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, Uuid
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
