import logging

from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from themed_chat.api.errors import error_response
from themed_chat.log_safety import log_exception

logger = logging.getLogger(__name__)


class InternalErrorMiddleware:
    """The last stop for unhandled exceptions: log them safely and answer 500.

    Starlette's ServerErrorMiddleware re-raises after its handler, and uvicorn then logs
    the exception with its full text, which for a database error can quote stored rows.
    This middleware runs inside it and never re-raises, so the only log entry is the one
    written by log_exception.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = finished = False

        async def tracking_send(message: Message) -> None:
            nonlocal started, finished
            if message["type"] == "http.response.start":
                started = True
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as error:
            log_exception(
                logger,
                "Unhandled error on %s %s: %s",
                error,
                scope.get("method", "?"),
                scope.get("path", "?"),
            )
            if finished:
                return  # The response is complete: logging is all that is left to do.
            if started:
                # Too late for a new response: end the body so the client is not left waiting.
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            path: str = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                response: Response = error_response(500, "internal_error")
            else:
                response = PlainTextResponse("Internal Server Error", status_code=500)
            await response(scope, receive, send)
