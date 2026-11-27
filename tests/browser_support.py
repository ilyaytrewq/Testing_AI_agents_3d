"""Helpers for the browser tests: a keyword-driven stub model and a login routine."""

import asyncio

from playwright.async_api import Page, expect

from themed_chat.chat.service import GenerationError

ACCESS_KEY = "browser_test_key"
REPLY = "Возьмите 15 г кофе на 250 г воды."
MARKDOWN_REPLY = """# Рецепт
Возьмите **15 г** кофе, *мелкий* помол и `250 г` воды.

- первый шаг
- второй шаг

1. раз
2. два

```
<b>не тег</b>
```"""
HTML_REPLY = "<img src=x onerror=alert(1)> и <script>alert(2)</script>"


class BrowserGenerator:
    """Answers by keyword, so each test chooses the behaviour it needs."""

    async def generate(self, text: str) -> str:
        if text.startswith("медленно"):
            await asyncio.sleep(0.8)
        if text == "ошибка":
            raise GenerationError("Simulated provider error.")
        if text == "markdown":
            return MARKDOWN_REPLY
        if text == "html":
            return HTML_REPLY
        return REPLY


async def sign_in(page: Page, url: str, key: str = ACCESS_KEY) -> None:
    await page.goto(url)
    await page.get_by_label("Ключ доступа").fill(key)
    await page.get_by_role("button", name="Войти").click()
    await expect(page.get_by_label("Сообщение")).to_be_visible()
