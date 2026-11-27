import asyncio
from collections.abc import AsyncIterator
from os import environ
from socket import AF_INET, SOCK_STREAM, socket

import pytest
import uvicorn
from browser_support import ACCESS_KEY, BrowserGenerator
from playwright.async_api import Browser, Page, async_playwright
from pydantic import SecretStr
from support import make_settings

from themed_chat.app import Overrides, create_app
from themed_chat.settings import AuthSettings, ChatSettings


@pytest.fixture
async def web_url(postgres_dsn: SecretStr) -> AsyncIterator[str]:
    with socket(AF_INET, SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        address, port = listener.getsockname()[:2]
        base_url = f"http://{address}:{port}"
        settings = make_settings(
            access_key=ACCESS_KEY,
            database_url=postgres_dsn.get_secret_value(),
            auth=AuthSettings(public_origin=base_url),
            chat=ChatSettings(message_limit=1000),
        )
        app = create_app(settings, Overrides(generator=BrowserGenerator()))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", ws="none"))
        running = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if running.done():
                        await running
                        raise RuntimeError("Test server failed to start.")
                    await asyncio.sleep(0.01)
            yield base_url
        finally:
            server.should_exit = True
            await asyncio.wait_for(running, timeout=10)


@pytest.fixture
async def browser() -> AsyncIterator[Browser]:
    async with async_playwright() as playwright:
        chromium = await playwright.chromium.launch(
            executable_path=environ.get("BROWSER_EXECUTABLE")
        )
        try:
            yield chromium
        finally:
            await chromium.close()


@pytest.fixture
async def page(browser: Browser) -> AsyncIterator[Page]:
    context = await browser.new_context(viewport={"width": 390, "height": 844})
    try:
        yield await context.new_page()
    finally:
        await context.close()
