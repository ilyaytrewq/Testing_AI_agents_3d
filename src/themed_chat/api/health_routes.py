import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from themed_chat.chat.ports import ChatRepository

logger = logging.getLogger(__name__)

READINESS_TIMEOUT_SECONDS = 3


def health_routes(repository: ChatRepository) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    async def live() -> dict[str, str]:
        """Liveness: the process answers; it does not touch the database."""
        return {"status": "ok"}

    @router.get("/readyz")
    async def ready(request: Request) -> JSONResponse:
        """Readiness: the service is initialized and the database answers."""
        if request.app.state.chat_service is None:
            return JSONResponse({"status": "starting"}, status_code=503)
        try:
            async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
                await repository.ping()
        except Exception as error:
            logger.warning("Readiness check failed: %s", type(error).__name__)
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    return router
