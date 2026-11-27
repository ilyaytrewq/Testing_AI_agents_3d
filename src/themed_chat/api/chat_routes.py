import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints, field_serializer

from themed_chat.api.errors import ApiError
from themed_chat.api.rate_limit import RateLimiter
from themed_chat.chat.models import (
    DEFAULT_PAGE_SIZE,
    MAX_MESSAGE_LENGTH,
    MAX_PAGE_SIZE,
    Turn,
    TurnStatus,
)
from themed_chat.chat.service import ChatService, GenerationError, GenerationTimeout, InvalidMessage

logger = logging.getLogger(__name__)

MAX_TURN_ID = 2**31 - 1
MAX_REVISION = 2**63 - 1


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    ]


class MessageOutput(BaseModel):
    id: str
    turn_id: int
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime
    # Display order is (question_at, turn_id); both messages of a turn share it.
    question_at: datetime
    status: TurnStatus
    is_mine: bool

    @field_serializer("created_at", "question_at")
    def fixed_width_utc(self, value: datetime) -> str:
        # Same width for every value, so the client can sort these strings as times.
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class HistoryOutput(BaseModel):
    title: str
    messages: list[MessageOutput]
    has_more: bool
    # Poll with ?after_revision=<this> to get every turn written later.
    revision: int


class TurnOutput(BaseModel):
    messages: list[MessageOutput]


def current_guest(request: Request) -> UUID:
    # The authentication middleware has put the guest here.
    guest: UUID | None = getattr(request.state, "guest_id", None)
    if guest is None:
        raise ApiError(401, "unauthorized")
    return guest


def chat_service(request: Request) -> ChatService:
    service: ChatService | None = request.app.state.chat_service
    if service is None:
        raise ApiError(503, "service_unavailable")
    return service


Guest = Annotated[UUID, Depends(current_guest)]
Service = Annotated[ChatService, Depends(chat_service)]


def _messages(turn: Turn, guest: UUID) -> list[MessageOutput]:
    shared = {"turn_id": turn.id, "question_at": turn.question_at, "status": turn.status}
    messages = [
        MessageOutput(
            id=f"{turn.id}:user",
            role="user",
            text=turn.question,
            created_at=turn.question_at,
            is_mine=turn.user_id == guest,
            **shared,
        )
    ]
    if turn.answer is not None:
        messages.append(
            MessageOutput(
                id=f"{turn.id}:assistant",
                role="assistant",
                text=turn.answer,
                created_at=turn.answer_at,
                is_mine=False,
                **shared,
            )
        )
    return messages


def chat_routes(title: str, message_limiter: RateLimiter) -> APIRouter:
    router = APIRouter()

    @router.get("/api/messages")
    async def get_messages(
        guest: Guest,
        service: Service,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        before: Annotated[int | None, Query(ge=1, le=MAX_TURN_ID)] = None,
        after_revision: Annotated[int | None, Query(ge=0, le=MAX_REVISION)] = None,
    ) -> HistoryOutput:
        if before is not None and after_revision is not None:
            raise ApiError(422, "invalid_request")
        if after_revision is not None:
            page = await service.changes(after_revision=after_revision, limit=limit)
        else:
            page = await service.history(limit=limit, before=before)
        return HistoryOutput(
            title=title,
            messages=[message for turn in page.turns for message in _messages(turn, guest)],
            has_more=page.has_more,
            revision=page.revision,
        )

    @router.post("/api/messages", status_code=201)
    async def send_message(body: MessageInput, guest: Guest, service: Service) -> TurnOutput:
        retry_after = message_limiter.hit(str(guest))
        if retry_after is not None:
            logger.warning("Message rate limit reached for guest %s.", guest)
            raise ApiError(429, "too_many_requests", {"Retry-After": str(retry_after)})
        try:
            turn = await service.send(guest, body.text)
        except InvalidMessage:
            raise ApiError(422, "invalid_message") from None
        except GenerationTimeout:
            raise ApiError(504, "model_timeout") from None
        except GenerationError:
            raise ApiError(502, "model_unavailable") from None
        return TurnOutput(messages=_messages(turn, guest))

    return router
