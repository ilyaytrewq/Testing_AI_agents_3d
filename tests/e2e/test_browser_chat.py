import asyncio
from collections.abc import AsyncIterator
from os import environ
from socket import AF_INET, SOCK_STREAM, socket

import pytest
import uvicorn
from playwright.async_api import Route, async_playwright, expect
from pydantic import SecretStr

from themed_chat.app import create_app
from themed_chat.chat.service import GenerationError
from themed_chat.settings import (
    AppSettings,
    AuthSettings,
    ModelSettings,
    SecretSettings,
    Settings,
)

ACCESS_KEY = "browser_test_key"
QUESTION = "Как заварить фильтр?"
REPLY = "Возьмите 15 г кофе на 250 г воды."


class BrowserGenerator:
    async def generate(self, text: str) -> str:
        await asyncio.sleep(0.25)
        if text == "ошибка":
            raise GenerationError("Simulated provider error.")
        return REPLY


@pytest.fixture
async def web_url(postgres_dsn: SecretStr) -> AsyncIterator[str]:
    with socket(AF_INET, SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        address, port = listener.getsockname()[:2]
        base_url = f"http://{address}:{port}"
        settings = Settings(
            AppSettings(
                auth=AuthSettings(public_origin=base_url),
                llm=ModelSettings(
                    base_url="https://unused.test/v1", model="fixture", system_prompt="fixture"
                ),
            ),
            SecretSettings(
                APP_ACCESS_KEY=SecretStr(ACCESS_KEY),
                APP_SESSION_SECRET=SecretStr("long-test-secret-only-for-browser-testing"),
                LLM_API_KEY=SecretStr("unused-fixture-value"),
                DATABASE_URL=postgres_dsn,
            ),
        )
        app = create_app(settings, generator=BrowserGenerator())
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


@pytest.mark.anyio
async def test_browser_can_login_send_recover_and_reload(web_url: str) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=environ.get("BROWSER_EXECUTABLE")
        )
        try:
            page = await browser.new_page(viewport={"width": 390, "height": 844})
            await page.goto(web_url)
            key = page.get_by_label("Ключ доступа")
            enter = page.get_by_role("button", name="Войти")
            await expect(enter).to_be_disabled()
            await key.fill("wrong_key")
            await enter.click()
            await expect(page.get_by_text("Неверный ключ доступа.")).to_be_visible()
            await key.fill(ACCESS_KEY)
            await enter.click()
            message = page.get_by_label("Сообщение")
            send = page.get_by_role("button", name="Отправить")
            await expect(message).to_be_visible()
            await message.fill("   ")
            await expect(send).to_be_disabled()
            await message.fill(QUESTION)
            await send.click()
            await expect(send).to_be_disabled()
            await expect(page.get_by_text(REPLY)).to_be_visible()
            await expect(page.locator("time")).to_have_count(2)
            await page.reload()
            await expect(page.get_by_text(REPLY)).to_be_visible()
            await message.fill("ошибка")
            await send.click()
            await expect(
                page.get_by_text("Не удалось получить ответ. Попробуйте ещё раз.")
            ).to_be_visible()
            await expect(message).to_have_value("ошибка")
            await expect(send).to_be_enabled()
            await expect(page.locator("time")).to_have_count(2)

            async def lose_reply(route: Route) -> None:
                if route.request.method == "POST":
                    assert (await route.fetch()).status == 201
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/api/messages", lose_reply)
            await message.fill("Нужен ли бумажный фильтр?")
            await send.click()
            refresh = page.get_by_role("button", name="Сверить с историей")
            await expect(refresh).to_be_visible()
            await expect(send).to_be_disabled()
            await refresh.click()
            await expect(page.get_by_text("Нужен ли бумажный фильтр?", exact=True)).to_be_visible()
            await expect(message).to_have_value("Нужен ли бумажный фильтр?")
            await expect(send).to_be_disabled()
            await expect(page.locator("time")).to_have_count(4)
        finally:
            await browser.close()
