from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from themed_chat.adapters.database import create_database_engine, migrate_database
from themed_chat.adapters.gemini import connect_gemini
from themed_chat.adapters.sql_repository import SqlChatRepository, SqlGuestRepository
from themed_chat.api.auth_middleware import SESSION_COOKIE, AuthMiddleware
from themed_chat.api.chat_routes import chat_routes
from themed_chat.api.session_routes import session_routes
from themed_chat.chat.ports import ChatRepository, GuestRepository, TextGenerator
from themed_chat.chat.service import ChatService
from themed_chat.settings import Settings, load_settings


def create_app(
    settings: Settings | None = None,
    *,
    guests: GuestRepository | None = None,
    repository: ChatRepository | None = None,
    generator: TextGenerator | None = None,
) -> FastAPI:
    if (guests is None) != (repository is None):
        raise ValueError("Provide custom guest and chat repositories together.")
    configuration = settings if settings is not None else load_settings()
    engine = create_database_engine(configuration) if guests is None else None
    if engine is not None:
        sessions = async_sessionmaker(engine)
        guests = SqlGuestRepository(sessions)
        repository = SqlChatRepository(sessions)
    assert guests is not None and repository is not None
    store = repository
    service = ChatService(store, generator) if generator is not None else None

    def get_service() -> ChatService:
        if service is None:
            raise HTTPException(503, "service_not_ready")
        return service

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal service
        try:
            if engine is not None:
                await migrate_database(engine)
            if generator is not None:
                yield
            else:
                async with connect_gemini(
                    configuration.app.llm, configuration.secrets.gemini_api_key
                ) as gemini:
                    service = ChatService(store, gemini)
                    try:
                        yield
                    finally:
                        service = None
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(
        title="Themed Chat",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    app.state.settings = configuration

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": {"code": "invalid_request"}}, status_code=422)

    auth = configuration.app.auth
    app.add_middleware(
        AuthMiddleware,
        access_key=configuration.secrets.access_key.get_secret_value(),
        public_origin=auth.public_origin,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=configuration.secrets.session_secret.get_secret_value(),
        session_cookie=SESSION_COOKIE,
        max_age=auth.session_ttl_seconds,
        path="/api",
        https_only=auth.cookie_secure,
    )
    app.include_router(session_routes(guests))
    app.include_router(chat_routes(get_service, configuration.app.chat.title))

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
