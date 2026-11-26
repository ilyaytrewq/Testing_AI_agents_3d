from fastapi import FastAPI

from themed_chat.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else load_settings()
    app = FastAPI(title="Themed Chat", docs_url=None, redoc_url=None, openapi_url=None)

    app.state.settings = configuration

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
