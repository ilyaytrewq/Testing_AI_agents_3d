from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response

from themed_chat.api.auth_middleware import SESSION_ID, SESSION_PATH, session_id
from themed_chat.api.credentials import Credentials
from themed_chat.api.guest_cookie import GuestCookie
from themed_chat.chat.models import GuestSession
from themed_chat.chat.ports import GuestRepository, SessionRepository


def session_routes(
    guests: GuestRepository,
    sessions: SessionRepository,
    credentials: Credentials,
    guest_cookie: GuestCookie,
    session_ttl_seconds: int,
) -> APIRouter:
    router = APIRouter()

    async def resolve_guest(request: Request, now: datetime) -> UUID:
        current = session_id(request.session)
        if current is not None:
            active = await sessions.active_session(current, credentials.fingerprint, now)
            if active is not None:
                await sessions.revoke_session(current, now)  # Replaced by the new session.
                return active.guest_id
        remembered = guest_cookie.read(request)
        if remembered is not None and await guests.exists(remembered):
            return remembered
        # Each login without a known guest creates one.
        guest_id = uuid4()
        await guests.create(guest_id)
        return guest_id

    @router.post(SESSION_PATH, status_code=204)
    async def login(request: Request) -> Response:
        # The middleware has already checked the access key.
        now = datetime.now(UTC)
        guest_id = await resolve_guest(request, now)
        new = GuestSession(
            uuid4(),
            guest_id,
            credentials.fingerprint,
            now,
            now + timedelta(seconds=session_ttl_seconds),
        )
        await sessions.create_session(new)
        request.session.clear()
        request.session[SESSION_ID] = str(new.id)
        response = Response(status_code=204)
        guest_cookie.write(response, guest_id)
        return response

    @router.delete(SESSION_PATH, status_code=204)
    async def logout(request: Request) -> Response:
        # The row is revoked, so a copy of the cookie stops working too. The guest cookie
        # stays and keeps "mine" labels stable.
        current = session_id(request.session)
        if current is not None:
            await sessions.revoke_session(current, datetime.now(UTC))
        request.session.clear()
        return Response(status_code=204)

    return router
