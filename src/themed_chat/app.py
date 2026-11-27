import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from asyncpg import InterfaceError, InternalClientError, PostgresError
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from themed_chat.adapters.database import create_database_engine, migrate_database
from themed_chat.adapters.providers import connect_function
from themed_chat.adapters.sql_repository import (
    SqlChatRepository,
    SqlGuestRepository,
    SqlSessionRepository,
)
from themed_chat.api.auth_middleware import SESSION_COOKIE, AuthMiddleware
from themed_chat.api.chat_routes import chat_routes
from themed_chat.api.credentials import Credentials
from themed_chat.api.errors import install_error_handlers
from themed_chat.api.guest_cookie import GuestCookie
from themed_chat.api.health_routes import health_routes
from themed_chat.api.internal_errors import InternalErrorMiddleware
from themed_chat.api.rate_limit import RateLimiter
from themed_chat.api.session_routes import session_routes
from themed_chat.chat.guard import GuardPolicy, TopicGuard
from themed_chat.chat.ports import (
    ChatRepository,
    Completion,
    GuestRepository,
    SessionRepository,
    TextGenerator,
)
from themed_chat.chat.service import ChatService
from themed_chat.settings import ConfigurationError, Settings, load_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Storage:
    guests: GuestRepository
    chat: ChatRepository
    sessions: SessionRepository


@dataclass(frozen=True, slots=True)
class Overrides:
    """Replacements for the real PostgreSQL storage and LLM client, used by tests.

    With a test generator the topic guard runs only if a test classifier is given too.
    """

    storage: Storage | None = None
    generator: TextGenerator | None = None
    classifier: Completion | None = None


def build_guard(settings: Settings, classifier: Completion | None) -> TopicGuard | None:
    guard = settings.app.guard
    if not guard.enabled or classifier is None:
        return None
    policy = GuardPolicy(
        refusals=dict(guard.refusals),
        default_language=guard.default_refusal_language,
        classifier_max_tokens=guard.classifier_max_tokens,
        structured_output=guard.structured_output,
        no_verdict_outage_threshold=guard.no_verdict_outage_threshold,
    )
    return TopicGuard(classifier, policy)


def configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
    # Their INFO records contain request URLs; keep them out of the logs.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_model_targets(configuration: Settings) -> None:
    """Name the hosts that receive API keys, so a key/URL mix-up shows at startup."""
    llm = configuration.app.llm
    logger.info("Model API: host=%s model=%s", urlsplit(llm.base_url).hostname, llm.model)
    if configuration.app.guard.enabled:
        classifier = configuration.classifier_model_settings
        logger.info(
            "Topic classifier API: host=%s model=%s",
            urlsplit(classifier.base_url).hostname,
            classifier.model,
        )


def create_app(settings: Settings | None = None, overrides: Overrides | None = None) -> FastAPI:
    configure_logging()
    configuration = settings if settings is not None else load_settings()
    overrides = overrides if overrides is not None else Overrides()
    connect = connect_function(configuration.app.llm.provider)
    engine = None
    if overrides.storage is None:
        engine = create_database_engine(configuration)
        sessions = async_sessionmaker(engine)
        storage = Storage(
            SqlGuestRepository(sessions),
            SqlChatRepository(sessions),
            SqlSessionRepository(sessions),
        )
    else:
        storage = overrides.storage

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            if engine is not None:
                try:
                    await migrate_database(engine)
                except (
                    OSError,
                    SQLAlchemyError,
                    InterfaceError,
                    InternalClientError,
                    PostgresError,
                ):
                    raise ConfigurationError(
                        "Could not initialize PostgreSQL. "
                        "Check connectivity and database permissions."
                    ) from None
            if overrides.generator is not None:
                yield
            else:
                log_model_targets(configuration)
                async with AsyncExitStack() as clients:
                    generator = await clients.enter_async_context(
                        connect(configuration.app.llm, configuration.secrets.llm_api_key)
                    )
                    classifier = None
                    if configuration.app.guard.enabled:
                        # Its own HTTP client, closed with the app; deterministic replies.
                        classifier = await clients.enter_async_context(
                            connect(
                                configuration.classifier_model_settings,
                                configuration.classifier_api_key,
                                temperature=0,
                            )
                        )
                    app.state.chat_service = ChatService(
                        storage.chat, generator, build_guard(configuration, classifier)
                    )
                    try:
                        yield
                    finally:
                        app.state.chat_service = None
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
    # Routes read the service from here. A test generator is ready without the lifespan.
    app.state.chat_service = (
        ChatService(
            storage.chat, overrides.generator, build_guard(configuration, overrides.classifier)
        )
        if overrides.generator is not None
        else None
    )
    install_error_handlers(app)

    auth = configuration.app.auth
    chat = configuration.app.chat
    secrets = configuration.secrets
    credentials = Credentials(
        secrets.access_key.get_secret_value(), secrets.session_secret.get_secret_value()
    )
    guest_cookie = GuestCookie(secrets.session_secret.get_secret_value(), secure=auth.cookie_secure)
    app.add_middleware(
        AuthMiddleware,
        credentials=credentials,
        sessions=storage.sessions,
        public_origin=auth.public_origin,
        login_limiter=RateLimiter(auth.login_attempts, auth.login_window_seconds),
        trusted_proxies=auth.trusted_proxies,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=secrets.session_secret.get_secret_value(),
        session_cookie=SESSION_COOKIE,
        max_age=auth.session_ttl_seconds,
        path="/api",
        https_only=auth.cookie_secure,
    )
    # Added last, so it wraps every other middleware (only ServerErrorMiddleware is outside).
    app.add_middleware(InternalErrorMiddleware)
    app.include_router(
        session_routes(
            storage.guests,
            storage.sessions,
            credentials,
            guest_cookie,
            auth.session_ttl_seconds,
        )
    )
    app.include_router(
        chat_routes(chat.title, RateLimiter(chat.message_limit, chat.message_window_seconds))
    )
    app.include_router(health_routes(storage.chat))
    web = Path(__file__).resolve().parent / "web"
    app.mount("/static", StaticFiles(directory=web / "static"), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            web / "index.html",
            headers={
                "Content-Security-Policy": (
                    "default-src 'self'; base-uri 'none'; object-src 'none'; "
                    "frame-ancestors 'none'; form-action 'none'"
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app
