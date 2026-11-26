from importlib import import_module
from importlib.util import find_spec

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.anyio
async def test_installed_app_serves_health_check() -> None:
    module_name = "themed_chat.app"
    assert find_spec(module_name) is not None, "the application factory is not installed"
    app = import_module(module_name).create_app()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
