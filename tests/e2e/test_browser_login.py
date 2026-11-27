import pytest
from browser_support import ACCESS_KEY, sign_in
from playwright.async_api import Page, Route, expect


@pytest.mark.anyio
async def test_login_page_is_visible_before_scripts_and_validates_the_key(
    page: Page, web_url: str
) -> None:
    async def block(route: Route) -> None:
        await route.abort()

    await page.route("**/static/*.js", block)
    await page.goto(web_url)
    await expect(page.get_by_role("heading", name="Загружаем чат")).to_be_visible()
    await page.unroute("**/static/*.js")
    await page.reload()
    key = page.get_by_label("Ключ доступа")
    enter = page.get_by_role("button", name="Войти")
    problem = page.locator("#login-error")
    await expect(enter).to_be_disabled()
    await expect(problem).to_have_text("")

    cases = [
        ("1234567", "слишком короткий", False),
        ("12345678", "", True),
        ("a" * 255, "", True),
        ("a" * 256, "слишком длинный", False),
        ("ключ-доступа", "только латинские буквы", False),
        ("has space 1", "только латинские буквы", False),
        ("emoji-key-😀", "только латинские буквы", False),
        ("", "", False),
    ]
    for value, message, valid in cases:
        await key.fill(value)
        if message:
            await expect(problem).to_contain_text(message)
            await expect(key).to_have_attribute("aria-invalid", "true")
        else:
            await expect(problem).to_have_text("")
            await expect(key).to_have_attribute("aria-invalid", "false")
        if valid:
            await expect(enter).to_be_enabled()
        else:
            await expect(enter).to_be_disabled()


@pytest.mark.anyio
async def test_wrong_key_shows_the_server_message_and_right_key_opens_the_chat(
    page: Page, web_url: str
) -> None:
    await page.goto(web_url)
    key = page.get_by_label("Ключ доступа")
    await key.fill("wrong_key_1")
    await page.get_by_role("button", name="Войти").click()
    await expect(page.get_by_text("Неверный ключ доступа.")).to_be_visible()
    await key.fill("wrong_key_2")  # Typing replaces the server message.
    await expect(page.get_by_text("Неверный ключ доступа.")).to_be_hidden()
    await sign_in(page, web_url)
    await expect(page.get_by_role("button", name="Выйти")).to_be_visible()


@pytest.mark.anyio
async def test_login_works_from_the_localhost_name(page: Page, web_url: str) -> None:
    await sign_in(page, web_url.replace("127.0.0.1", "localhost"))


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "headers", "body", "message"),
    [
        (403, {}, {"error": {"code": "origin_not_allowed"}}, "адрес страницы не совпадает"),
        (
            429,
            {"Retry-After": "7"},
            {"error": {"code": "too_many_requests"}},
            "Слишком много попыток, подождите 7 с",
        ),
        (503, {}, {"error": {"code": "service_unavailable"}}, "временно недоступен"),
        (500, {}, {"error": {"code": "internal_error"}}, "Сервер недоступен, попробуйте позже"),
    ],
)
async def test_login_errors_have_clear_messages(
    page: Page, web_url: str, status: int, headers: dict[str, str], body: object, message: str
) -> None:
    async def reply(route: Route) -> None:
        await route.fulfill(status=status, headers=headers, json=body)

    await page.route("**/api/session", reply)
    await page.goto(web_url)
    await page.get_by_label("Ключ доступа").fill(ACCESS_KEY)
    await page.get_by_role("button", name="Войти").click()
    await expect(page.locator("#login-error")).to_contain_text(message)


@pytest.mark.anyio
async def test_login_is_rate_limited_by_the_server(page: Page, web_url: str) -> None:
    await page.goto(web_url)
    key = page.get_by_label("Ключ доступа")
    enter = page.get_by_role("button", name="Войти")
    for _ in range(10):
        await key.fill("wrong_key_1")
        await enter.click()
        await expect(page.get_by_text("Неверный ключ доступа.")).to_be_visible()
    await key.fill("wrong_key_1")
    await enter.click()
    await expect(page.locator("#login-error")).to_contain_text("Слишком много попыток, подождите")
