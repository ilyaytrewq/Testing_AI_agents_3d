from hmac import compare_digest
from uuid import UUID

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from themed_chat.settings import ACCESS_KEY_PATTERN

SESSION_PATH = "/api/session"
SESSION_COOKIE = "chat_session"


def session_guest(request: Request) -> UUID | None:
    candidate = request.session.get("guest_id")
    if isinstance(candidate, str):
        try:
            return UUID(candidate)
        except ValueError:
            return None
    return None


class AuthMiddleware:
    def __init__(self, app: ASGIApp, *, access_key: str, public_origin: str) -> None:
        self.app = app
        self.access_key = access_key.encode("ascii")
        self.public_origin = public_origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        root_path: str = scope.get("root_path", "")
        if root_path and path.startswith(f"{root_path}/"):
            path = path[len(root_path) :]
        if path != "/api" and not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def send_private(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        request = Request(scope)
        login = path == SESSION_PATH and request.method == "POST"
        if request.method not in {"GET", "HEAD"} and request.headers.getlist("origin") != [
            self.public_origin
        ]:
            response = JSONResponse({"error": {"code": "origin_not_allowed"}}, status_code=403)
            await response(scope, receive, send_private)
            return
        if login:
            candidates = request.headers.getlist("x-access-key")
            allowed = (
                len(candidates) == 1
                and ACCESS_KEY_PATTERN.fullmatch(candidates[0]) is not None
                and compare_digest(candidates[0].encode("ascii"), self.access_key)
            )
        else:
            allowed = session_guest(request) is not None
        if not allowed:
            response = JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
            await response(scope, receive, send_private)
            return
        await self.app(scope, receive, send_private)
