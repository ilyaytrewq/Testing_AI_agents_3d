from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.anyio
async def test_installed_app_serves_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ACCESS_KEY", "test-key")
    monkeypatch.setenv("APP_SESSION_SECRET", "unit-test-signing-secret-at-least-32-chars")
    monkeypatch.setenv("GEMINI_API_KEY", "test-provider-key")
    module_name = "themed_chat.app"
    assert find_spec(module_name) is not None, "the application factory is not installed"
    app = import_module(module_name).create_app()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_factory_rejects_missing_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from themed_chat.app import create_app
    from themed_chat.settings import ConfigurationError

    config = Path("config/app.yaml").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    Path("config").mkdir()
    Path("config/app.yaml").write_text(config, encoding="utf-8")
    for name in ("APP_ACCESS_KEY", "APP_SESSION_SECRET", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="APP_ACCESS_KEY"):
        create_app()
