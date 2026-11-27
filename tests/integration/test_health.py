from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from support import MemoryStorage, StubGenerator, client_for, make_settings

from themed_chat.app import create_app


@pytest.fixture
def deployment_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, postgres_dsn: SecretStr
) -> None:
    config_bytes = Path("config/app.yaml").read_bytes()
    monkeypatch.chdir(tmp_path)
    Path("config").mkdir()
    Path("config/app.yaml").write_bytes(config_bytes)
    monkeypatch.setenv("DATABASE_URL", postgres_dsn.get_secret_value())
    monkeypatch.setenv("APP_ACCESS_KEY", "test-key")
    monkeypatch.setenv("APP_SESSION_SECRET", "unit-test-signing-secret-at-least-32-chars")
    monkeypatch.setenv("LLM_API_KEY", "test-provider-key")


@pytest.mark.anyio
@pytest.mark.usefixtures("deployment_env")
async def test_installed_app_serves_health_checks() -> None:
    module_name = "themed_chat.app"
    assert find_spec(module_name) is not None, "the application factory is not installed"
    app = import_module(module_name).create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
    ):
        live = await client.get("/healthz")
        ready = await client.get("/readyz")
    assert live.status_code == 200 and live.json() == {"status": "ok"}
    assert ready.status_code == 200 and ready.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_readiness_follows_the_storage_while_liveness_does_not() -> None:
    storage = MemoryStorage()
    app = create_app(make_settings(), storage.overrides(StubGenerator()))
    async with client_for(app) as client:
        assert (await client.get("/readyz")).status_code == 200
        storage.healthy = False
        unavailable = await client.get("/readyz")
        assert unavailable.status_code == 503
        assert unavailable.json() == {"status": "unavailable"}
        assert (await client.get("/healthz")).status_code == 200


@pytest.mark.anyio
async def test_not_ready_until_the_model_client_is_created() -> None:
    app = create_app(make_settings(), MemoryStorage().overrides())
    async with client_for(app) as client:
        assert (await client.get("/readyz")).status_code == 503
        assert (await client.get("/healthz")).status_code == 200


def test_factory_rejects_missing_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from themed_chat.settings import ConfigurationError

    config = Path("config/app.yaml").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    Path("config").mkdir()
    Path("config/app.yaml").write_text(config, encoding="utf-8")
    for name in ("APP_ACCESS_KEY", "APP_SESSION_SECRET", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="APP_ACCESS_KEY"):
        create_app()
