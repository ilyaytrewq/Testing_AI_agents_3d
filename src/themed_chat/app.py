from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from themed_chat.api.auth_middleware import SESSION_COOKIE, AuthMiddleware
from themed_chat.api.session_routes import session_routes
from themed_chat.chat.ports import GuestRepository
from themed_chat.settings import Settings, load_settings


def create_app(
    settings: Settings | None = None, *, guests: GuestRepository | None = None
) -> FastAPI:
    configuration = settings if settings is not None else load_settings()
    app = FastAPI(
        title="Themed Chat", docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False
    )
    app.state.settings = configuration
    if guests is not None:
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
