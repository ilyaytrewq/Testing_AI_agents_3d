from uuid import uuid4

from fastapi import APIRouter, Request, Response

from themed_chat.api.auth_middleware import SESSION_PATH, session_guest
from themed_chat.chat.ports import GuestRepository


def session_routes(guests: GuestRepository) -> APIRouter:
    router = APIRouter()

    @router.post(SESSION_PATH, status_code=204)
    async def login(request: Request) -> Response:
        if session_guest(request) is None:
            guest_id = uuid4()
            await guests.create(guest_id)
            request.session["guest_id"] = str(guest_id)
        return Response(status_code=204)

    @router.get(SESSION_PATH, status_code=204)
    async def session_status() -> Response:
        return Response(status_code=204)

    return router
