import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from functools import wraps
from typing import Any
from uuid import UUID

from asyncpg import InterfaceError as AsyncpgInterfaceError
from asyncpg import InternalClientError, PostgresConnectionError
from asyncpg.exceptions import ConnectionDoesNotExistError
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Text,
    Uuid,
    delete,
    func,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from themed_chat.chat.errors import StorageUnavailable
from themed_chat.chat.models import GuestSession, NewTurn, Turn, TurnStatus

logger = logging.getLogger(__name__)

# Connection-level failures only: the database is down or the link broke. Anything else
# (IntegrityError, ProgrammingError, ...) is a bug and reaches the 500 handler.
CONNECTION_ERRORS = (
    OperationalError,
    InterfaceError,
    OSError,
    AsyncpgInterfaceError,
    InternalClientError,
    PostgresConnectionError,
    ConnectionDoesNotExistError,
)
# Serializes writes to chat_turns, so they commit in revision order.
TURN_WRITE_LOCK_ID = int.from_bytes(b"CHATTURN", "big") >> 1


def _connection_failure(error: Exception) -> bool:
    if isinstance(error, CONNECTION_ERRORS):
        return True
    return isinstance(error, DBAPIError) and error.connection_invalidated


def storage_errors[**P, R](
    method: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Report a lost database connection as StorageUnavailable, logging only its class."""

    @wraps(method)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await method(*args, **kwargs)
        except Exception as error:
            if not _connection_failure(error):
                raise
            logger.error("Database failure in %s: %s", method.__qualname__, type(error).__name__)
            raise StorageUnavailable("The database is unavailable.") from error

    return wrapper


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    guest_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SqlGuestRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @storage_errors
    async def create(self, guest_id: UUID) -> None:
        async with self.sessions.begin() as session:
            session.add(UserRow(id=guest_id, created_at=datetime.now(UTC)))

    @storage_errors
    async def exists(self, guest_id: UUID) -> bool:
        async with self.sessions() as session:
            return await session.get(UserRow, guest_id) is not None


class SqlSessionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @storage_errors
    async def create_session(self, guest_session: GuestSession) -> None:
        async with self.sessions.begin() as session:
            # Opportunistic pruning: logins are rare, so this stays cheap.
            await session.execute(
                delete(SessionRow).where(SessionRow.expires_at < guest_session.created_at)
            )
            session.add(
                SessionRow(
                    id=guest_session.id,
                    guest_id=guest_session.guest_id,
                    key_fingerprint=guest_session.key_fingerprint,
                    created_at=guest_session.created_at,
                    expires_at=guest_session.expires_at,
                )
            )

    @storage_errors
    async def active_session(
        self, session_id: UUID, key_fingerprint: str, now: datetime
    ) -> GuestSession | None:
        query = select(SessionRow).where(
            SessionRow.id == session_id,
            SessionRow.key_fingerprint == key_fingerprint,
            SessionRow.revoked_at.is_(None),
            SessionRow.expires_at > now,
        )
        async with self.sessions() as session:
            row = await session.scalar(query)
        if row is None:
            return None
        return GuestSession(
            row.id, row.guest_id, row.key_fingerprint, _utc(row.created_at), _utc(row.expires_at)
        )

    @storage_errors
    async def revoke_session(self, session_id: UUID, now: datetime) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(SessionRow)
                .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )


class ChatTurnRow(Base):
    __tablename__ = "chat_turns"
    # INSERT ... RETURNING the revision drawn from the sequence by the database.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("users.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    question_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answer_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(
        BigInteger,
        server_default=text("nextval('chat_turns_revision_seq')"),
        nullable=False,
        unique=True,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _status(value: str) -> TurnStatus:
    if value == "failed":
        return "failed"
    return "answered"


def _turn(row: ChatTurnRow) -> Turn:
    return Turn(
        row.id,
        row.user_id,
        row.question,
        row.answer,
        _utc(row.question_at),
        _utc(row.answer_at),
        _status(row.status),
        row.revision,
    )


class SqlChatRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @storage_errors
    async def list_turns(self, *, limit: int, before: int | None = None) -> list[Turn]:
        order = (ChatTurnRow.question_at.desc(), ChatTurnRow.id.desc())
        query = select(ChatTurnRow).order_by(*order).limit(limit)
        async with self.sessions() as session:
            if before is not None:
                anchor = await session.get(ChatTurnRow, before)
                if anchor is None:
                    return []
                query = query.where(
                    tuple_(ChatTurnRow.question_at, ChatTurnRow.id)
                    < tuple_(anchor.question_at, anchor.id)
                )
            turns = [_turn(row) for row in await session.scalars(query)]
        return turns[::-1]

    @storage_errors
    async def list_changes(self, *, after_revision: int, limit: int) -> list[Turn]:
        query = (
            select(ChatTurnRow)
            .where(ChatTurnRow.revision > after_revision)
            .order_by(ChatTurnRow.revision)
            .limit(limit)
        )
        async with self.sessions() as session:
            return [_turn(row) for row in await session.scalars(query)]

    @storage_errors
    async def latest_revision(self) -> int:
        async with self.sessions() as session:
            value = await session.scalar(select(func.max(ChatTurnRow.revision)))
        return int(value or 0)

    @storage_errors
    async def append_turn(self, turn: NewTurn) -> Turn:
        async with self.sessions.begin() as session:
            # Held until commit: the revision drawn below commits before any later one.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": TURN_WRITE_LOCK_ID}
            )
            row = ChatTurnRow(
                user_id=turn.user_id,
                question=turn.question,
                answer=turn.answer,
                question_at=_utc(turn.question_at),
                answer_at=_utc(turn.answer_at),
                status=turn.status,
            )
            session.add(row)
            await session.flush()
            return _turn(row)

    @storage_errors
    async def ping(self) -> None:
        async with self.sessions() as session:
            await session.execute(text("SELECT 1"))
