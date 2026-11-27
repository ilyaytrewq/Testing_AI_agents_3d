import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from themed_chat.api.client_address import Network, client_address
from themed_chat.api.credentials import Credentials
from themed_chat.api.errors import error_response
from themed_chat.api.rate_limit import RateLimiter
from themed_chat.chat.errors import StorageUnavailable
from themed_chat.chat.ports import SessionRepository
from themed_chat.settings import ACCESS_KEY_PATTERN

logger = logging.getLogger(__name__)

SESSION_PATH = "/api/session"
SESSION_COOKIE = "chat_session"
LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_parts(origin: str) -> tuple[str, str, int] | None:
    """Return (scheme, host, port) for a bare origin, or None if it is anything else."""
    try:
        url = urlsplit(origin)
        if origin != f"{url.scheme}://{url.netloc}" or not url.hostname:
            return None
        port = url.port or DEFAULT_PORTS.get(url.scheme)
    except ValueError:
        return None
    return (url.scheme, url.hostname, port) if port is not None else None


def origin_allowed(origin: str, public_origin: str) -> bool:
    """Exact match; when the public origin is a loopback address, any loopback name matches."""
    if origin == public_origin:
        return True
    expected = _origin_parts(public_origin)
    actual = _origin_parts(origin)
    if expected is None or actual is None:
        return False
    return (
        expected[1] in LOOPBACK_NAMES
        and actual[1] in LOOPBACK_NAMES
        and (expected[0], expected[2]) == (actual[0], actual[2])
    )


SESSION_ID = "sid"


def session_id(session: Mapping[str, Any]) -> UUID | None:
    """The server-side session id carried by the signed cookie, if well-formed."""
    value = session.get(SESSION_ID)
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


class AuthMiddleware:
    """Guards /api: Origin check for state changes, key check at login, session otherwise."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        credentials: Credentials,
        sessions: SessionRepository,
        public_origin: str,
        login_limiter: RateLimiter,
        trusted_proxies: Sequence[Network] = (),
    ) -> None:
        self.app = app
        self.credentials = credentials
        self.sessions = sessions
        self.public_origin = public_origin
        self.login_limiter = login_limiter
        self.trusted_proxies = tuple(trusted_proxies)

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
        try:
            rejection = await self._reject(request, path)
        except StorageUnavailable:
            # Exception handlers run inside the app; this middleware is outside it.
            rejection = error_response(503, "service_unavailable")
        if rejection is not None:
            await rejection(scope, receive, send_private)
            return
        await self.app(scope, receive, send_private)

    async def _reject(self, request: Request, path: str) -> JSONResponse | None:
        request.state.client_address = client_address(request, self.trusted_proxies)
        if request.method not in {"GET", "HEAD"}:
            origins = request.headers.getlist("origin")
            if len(origins) != 1 or not origin_allowed(origins[0], self.public_origin):
                return error_response(403, "origin_not_allowed")
        if path == SESSION_PATH and request.method == "POST":
            return self._reject_login(request)
        if path == SESSION_PATH and request.method == "DELETE":
            return None  # Logging out must work even when the session is already invalid.
        current = session_id(request.session)
        found = (
            await self.sessions.active_session(
                current, self.credentials.fingerprint, datetime.now(UTC)
            )
            if current is not None
            else None
        )
        if found is None:
            return error_response(401, "unauthorized")
        request.state.guest_id = found.guest_id
        return None

    def _reject_login(self, request: Request) -> JSONResponse | None:
        client = request.state.client_address
        retry_after = self.login_limiter.hit(client)
        if retry_after is not None:
            logger.warning("Login rate limit reached for client %s.", client)
            return error_response(429, "too_many_requests", {"Retry-After": str(retry_after)})
        candidates = request.headers.getlist("x-access-key")
        if (
            len(candidates) == 1
            and ACCESS_KEY_PATTERN.fullmatch(candidates[0]) is not None
            and self.credentials.accepts(candidates[0])
        ):
            return None
        logger.info("Rejected login attempt from client %s.", client)
        return error_response(401, "unauthorized")
