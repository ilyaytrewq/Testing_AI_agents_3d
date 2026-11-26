from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from themed_chat.api.auth_middleware import session_guest
from themed_chat.chat.models import MAX_MESSAGE_LENGTH, Turn
from themed_chat.chat.service import ChatService, GenerationError, GenerationTimeout, InvalidMessage


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    ]


class MessageOutput(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime
    is_mine: bool


class HistoryOutput(BaseModel):
    title: str
    messages: list[MessageOutput]


class TurnOutput(BaseModel):
    messages: list[MessageOutput]


def _guest(request: Request) -> UUID:
    guest = session_guest(request)
    if guest is None:
        raise HTTPException(401, "unauthorized")
    return guest


def _messages(turn: Turn, guest: UUID) -> list[MessageOutput]:
    draft = turn.draft
    return [
        MessageOutput(
            id=f"{turn.id}:user",
            role="user",
            text=draft.question,
            created_at=draft.question_at,
            is_mine=draft.user_id == guest,
        ),
        MessageOutput(
            id=f"{turn.id}:assistant",
            role="assistant",
            text=draft.answer,
            created_at=draft.answer_at,
            is_mine=False,
        ),
    ]


def chat_routes(service: ChatService, title: str) -> APIRouter:
    router = APIRouter()

    @router.get("/api/messages")
    async def get_messages(request: Request) -> HistoryOutput:
        guest = _guest(request)
        return HistoryOutput(
            title=title,
            messages=[
                message for turn in await service.history() for message in _messages(turn, guest)
            ],
        )

    @router.post("/api/messages", status_code=201)
    async def send_message(body: MessageInput, request: Request) -> TurnOutput:
        guest = _guest(request)
        try:
            turn = await service.send(guest, body.text)
        except InvalidMessage:
            raise HTTPException(422, "invalid_message") from None
        except GenerationTimeout:
            raise HTTPException(504, "model_timeout") from None
        except GenerationError:
            raise HTTPException(502, "model_unavailable") from None
        return TurnOutput(messages=_messages(turn, guest))

    return router
