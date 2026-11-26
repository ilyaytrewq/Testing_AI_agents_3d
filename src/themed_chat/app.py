from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from themed_chat.adapters.database import create_database_engine, migrate_database
from themed_chat.adapters.sql_repository import SqlGuestRepository
from themed_chat.api.auth_middleware import SESSION_COOKIE, AuthMiddleware
from themed_chat.api.session_routes import session_routes
from themed_chat.chat.ports import GuestRepository
from themed_chat.settings import Settings, load_settings


def create_app(
    settings: Settings | None = None, *, guests: GuestRepository | None = None
) -> FastAPI:
    configuration = settings if settings is not None else load_settings()
    engine = create_database_engine(configuration) if guests is None else None
    if guests is None:
        assert engine is not None
        guests = SqlGuestRepository(async_sessionmaker(engine))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            if engine is not None:
                await migrate_database(engine)
            yield
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

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
