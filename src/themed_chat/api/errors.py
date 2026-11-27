import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from themed_chat.chat.errors import StorageUnavailable

logger = logging.getLogger(__name__)

HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}


class ApiError(Exception):
    """An error with a stable machine-readable code, sent as {"error": {"code": ...}}."""

    def __init__(
        self, status_code: int, code: str, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.headers = headers


def error_response(
    status_code: int, code: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code}},
        status_code=status_code,
        headers={"Cache-Control": "no-store", **(headers or {})},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError) -> JSONResponse:
        return error_response(error.status_code, error.code, error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return error_response(422, "invalid_request")

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        code = HTTP_ERROR_CODES.get(error.status_code, "http_error")
        return error_response(error.status_code, code, error.headers)

    @app.exception_handler(StorageUnavailable)
    async def database_error(request: Request, error: StorageUnavailable) -> JSONResponse:
        # The adapter already logged the cause; this records which request failed.
        logger.error(
            "Database failure on %s %s: %s",
            request.method,
            request.url.path,
            type(error.__cause__).__name__,
        )
        return error_response(503, "service_unavailable")
