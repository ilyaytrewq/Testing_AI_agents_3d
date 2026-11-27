import asyncio
import re

import pytest
from browser_support import ACCESS_KEY, HTML_REPLY, REPLY, sign_in
from playwright.async_api import Browser, Page, Route, expect

QUESTION = "Как заварить фильтр?"


def parts(page: Page) -> tuple[object, object]:
    return page.get_by_label("Сообщение"), page.get_by_role("button", name="Отправить")


@pytest.mark.anyio
async def test_send_shows_the_question_at_once_then_the_answer(page: Page, web_url: str) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)
    await message.fill("   \n ")
    await expect(send).to_be_disabled()
    await message.press("Enter")
    await expect(page.locator("#messages li, #pending li")).to_have_count(0)

    await message.fill("медленно: " + QUESTION)
    await send.click()
    pending = page.locator("#pending .message.pending")
    await expect(pending).to_contain_text("медленно: " + QUESTION)
    await expect(pending).to_contain_text("Отправляется")
    await expect(page.get_by_text("печатает…")).to_be_visible()
    await expect(send).to_be_disabled()
    await expect(message).to_have_value("")
    await expect(page.get_by_text(REPLY)).to_be_visible()
    await expect(page.locator("#pending li")).to_have_count(0)
    await expect(page.locator("#messages li")).to_have_count(2)

    times = page.locator("#messages time")
    await expect(times).to_have_count(2)
    for index in range(2):
        stamp = times.nth(index)
        assert await stamp.get_attribute("datetime")
        assert re.search(r"\d{2}\.\d{2}\.\d{2,4}.*\d{1,2}:\d{2}", await stamp.inner_text())
    await page.reload()
    await expect(page.get_by_text(REPLY)).to_be_visible()
    await expect(page.locator("#messages li")).to_have_count(2)


@pytest.mark.anyio
async def test_enter_sends_and_shift_enter_adds_a_line(page: Page, web_url: str) -> None:
    await sign_in(page, web_url)
    message, _ = parts(page)
    await message.fill("первая строка")
    await message.press("Shift+Enter")
    await message.type("вторая строка")
    await expect(message).to_have_value("первая строка\nвторая строка")
    await expect(page.locator("#messages li")).to_have_count(0)
    await message.press("Enter")
    body = page.locator("#messages .message.mine .message-body")
    await expect(body).to_have_text("первая строка\nвторая строка")
    await expect(page.get_by_text(REPLY)).to_be_visible()
    await expect(page.get_by_text("Enter — отправить, Shift+Enter — новая строка.")).to_be_visible()


@pytest.mark.anyio
async def test_message_length_limit_counts_characters(page: Page, web_url: str) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)
    problem = page.locator("#message-error")
    await message.fill("x" * 500)
    await expect(page.locator("#message-count")).to_have_text("500 / 500")
    await expect(send).to_be_enabled()
    await expect(problem).to_have_text("")
    await message.fill("x" * 501)
    await expect(page.locator("#message-count")).to_have_text("501 / 500")
    await expect(send).to_be_disabled()
    await expect(problem).to_contain_text("длиннее 500 символов")
    await expect(message).to_have_attribute("aria-invalid", "true")
    assert len(await message.input_value()) == 501  # Nothing is silently cut off.
    # Emoji take two UTF-16 units each but count as one character, like on the server.
    await message.fill("😀" * 500)
    await expect(send).to_be_enabled()
    await expect(problem).to_have_text("")
    await send.click()
    await expect(page.get_by_text(REPLY)).to_be_visible()


@pytest.mark.anyio
async def test_assistant_markdown_is_rendered_and_html_stays_text(page: Page, web_url: str) -> None:
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: dialogs.append(dialog.message))
    await sign_in(page, web_url)
    message, send = parts(page)
    await message.fill("markdown")
    await send.click()
    answer = page.locator("#messages .message:not(.mine) .markdown")
    await expect(answer.locator("strong").nth(1)).to_have_text("15 г")
    await expect(answer.locator("em")).to_have_text("мелкий")
    await expect(answer.locator("code").first).to_have_text("250 г")
    await expect(answer.locator("ul li")).to_have_text(["первый шаг", "второй шаг"])
    await expect(answer.locator("ol li")).to_have_text(["раз", "два"])
    await expect(answer.locator("pre code")).to_have_text("<b>не тег</b>")
    await expect(answer.locator("b")).to_have_count(0)

    await message.fill("html")
    await send.click()
    await expect(page.get_by_text(HTML_REPLY, exact=True)).to_be_visible()
    await expect(page.locator("#messages img, #messages script")).to_have_count(0)
    await message.fill("<img src=x onerror=alert(3)>")
    await send.click()
    await expect(page.get_by_text("<img src=x onerror=alert(3)>", exact=True)).to_be_visible()
    await expect(page.locator("#messages img")).to_have_count(0)
    assert dialogs == []


@pytest.mark.anyio
async def test_failed_question_stays_marked_and_can_be_retried(page: Page, web_url: str) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)
    await message.fill("ошибка")
    await send.click()
    # The server saved the question as unanswered; it replaces the pending entry.
    failed = page.locator("#messages .message.failed")
    await expect(failed).to_contain_text("ошибка")
    await expect(failed).to_contain_text("Ответ не получен")
    await expect(page.get_by_text("Не удалось получить ответ. Попробуйте ещё раз.")).to_be_visible()
    await expect(message).to_have_value("ошибка")
    await expect(send).to_be_enabled()
    await expect(page.locator("#pending li")).to_have_count(0)
    await expect(page.locator("#messages li")).to_have_count(1)
    await message.fill(QUESTION)
    await send.click()
    await expect(page.get_by_text(REPLY)).to_be_visible()
    await expect(page.locator("#pending li")).to_have_count(0)
    await expect(page.locator("#messages li")).to_have_count(3)
    # After a reload the failed question is still there, marked, with no duplicate.
    await page.reload()
    await expect(page.locator("#messages li")).to_have_count(3)
    await expect(page.locator("#messages .message.failed")).to_have_count(1)
    await expect(page.locator("#messages .message.failed")).to_contain_text("Ответ не получен")
    await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    await expect(page.locator("#messages li")).to_have_count(3)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "headers", "code", "text"),
    [
        (429, {"Retry-After": "7"}, "too_many_requests", "Слишком много сообщений, подождите 7 с"),
        (503, {}, "service_unavailable", "Сервис временно недоступен"),
        (504, {}, "model_timeout", "Ассистент не успел ответить"),
        (500, {}, "internal_error", "Сервер недоступен, попробуйте позже"),
        (422, {}, "invalid_message", "Проверьте текст сообщения"),
        (403, {}, "origin_not_allowed", "адрес страницы не совпадает"),
    ],
)
async def test_server_errors_have_clear_messages(
    page: Page, web_url: str, status: int, headers: dict[str, str], code: str, text: str
) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)

    async def fail(route: Route) -> None:
        if route.request.method == "POST":
            await route.fulfill(status=status, headers=headers, json={"error": {"code": code}})
        else:
            await route.continue_()

    await page.route("**/api/messages", fail)
    await message.fill(QUESTION)
    await send.click()
    await expect(page.locator("#chat-error")).to_contain_text(text)
    await expect(page.locator("#pending .message.failed")).to_have_count(1)
    await expect(message).to_have_value(QUESTION)


@pytest.mark.anyio
async def test_lost_reply_is_checked_against_history_automatically(
    page: Page, web_url: str
) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)

    async def lose_reply(route: Route) -> None:
        if route.request.method == "POST":
            assert (await route.fetch()).status == 201
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/api/messages", lose_reply)
    await message.fill("Нужен ли бумажный фильтр?")
    await send.click()
    await expect(page.get_by_text(REPLY)).to_be_visible()
    await expect(page.locator("#messages .message.mine")).to_contain_text(
        "Нужен ли бумажный фильтр?"
    )
    await expect(page.locator("#pending li")).to_have_count(0)
    await expect(page.locator("#chat-error")).to_have_text("")
    await expect(send).to_be_disabled()  # The field is empty: delivered, nothing to retry.


@pytest.mark.anyio
async def test_request_that_never_arrived_can_be_retried(page: Page, web_url: str) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)

    async def drop(route: Route) -> None:
        if route.request.method == "POST":
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/api/messages", drop)
    await message.fill(QUESTION)
    await send.click()
    await expect(page.locator("#chat-error")).to_contain_text("нет подтверждения от сервера")
    await expect(page.locator("#pending .message.failed")).to_contain_text("Ответ не получен")
    await expect(message).to_have_value(QUESTION)
    await expect(send).to_be_enabled()
    await page.unroute("**/api/messages")
    await send.click()
    await expect(page.get_by_text(REPLY)).to_be_visible()
    await expect(page.locator("#messages li")).to_have_count(2)


@pytest.mark.anyio
async def test_expired_session_returns_to_the_login_screen(page: Page, web_url: str) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)
    await page.context.clear_cookies()
    await message.fill(QUESTION)
    await send.click()
    await expect(page.get_by_role("heading", name="Вход по ключу")).to_be_visible()
    await expect(page.locator("#login-error")).to_have_text("Сессия истекла. Войдите снова.")
    await expect(page.locator("#chat")).to_be_hidden()


@pytest.mark.anyio
async def test_logout_returns_to_login_and_keeps_authorship_on_return(
    page: Page, web_url: str
) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)
    await message.fill(QUESTION)
    await send.click()
    await expect(page.get_by_text(REPLY)).to_be_visible()

    await page.get_by_role("button", name="Выйти").click()
    await expect(page.get_by_role("heading", name="Вход по ключу")).to_be_visible()
    await expect(page.locator("#chat")).to_be_hidden()
    await page.reload()
    await expect(page.get_by_role("heading", name="Вход по ключу")).to_be_visible()

    await sign_in(page, web_url)
    await expect(page.locator("#messages .message.mine")).to_contain_text(QUESTION)
    await expect(page.get_by_text("Гость")).to_have_count(0)


@pytest.mark.anyio
async def test_other_participants_messages_appear_without_reload(
    page: Page, browser: Browser, web_url: str
) -> None:
    await sign_in(page, web_url)
    other = await browser.new_context()
    try:
        headers = {"Origin": web_url}
        login = await other.request.post(
            f"{web_url}/api/session", headers={**headers, "X-Access-Key": ACCESS_KEY}
        )
        assert login.status == 204
        sent = await other.request.post(
            f"{web_url}/api/messages", headers=headers, data={"text": "Вопрос соседа"}
        )
        assert sent.status == 201
    finally:
        await other.close()
    await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    neighbour = page.locator("#messages .message:not(.mine)", has_text="Вопрос соседа")
    await expect(neighbour).to_contain_text("Гость")
    await expect(page.get_by_text(REPLY)).to_be_visible()


@pytest.mark.anyio
async def test_older_history_is_loaded_on_demand_keeping_the_scroll_position(
    page: Page, web_url: str
) -> None:
    await sign_in(page, web_url)
    headers = {"Origin": web_url}
    for number in range(1, 56):
        sent = await page.request.post(
            f"{web_url}/api/messages", headers=headers, data={"text": f"вопрос {number}"}
        )
        assert sent.status == 201
    await page.reload()
    items = page.locator("#messages li")
    await expect(items).to_have_count(100)
    earlier = page.get_by_role("button", name="Показать более ранние")
    await expect(earlier).to_be_visible()
    await expect(page.get_by_text("вопрос 55", exact=True)).to_be_visible()

    scroller = page.locator("#transcript")
    anchor = page.locator('#messages li[data-turn-id="6"]').first
    await scroller.evaluate("node => { node.scrollTop = 0; }")
    before = await anchor.evaluate("node => node.getBoundingClientRect().top")
    await earlier.click()
    await expect(items).to_have_count(110)
    await expect(earlier).to_be_hidden()
    after = await anchor.evaluate("node => node.getBoundingClientRect().top")
    assert abs(after - before) < 3
    await expect(page.get_by_text("вопрос 1", exact=True)).to_have_count(1)


@pytest.mark.anyio
async def test_turns_from_others_during_a_send_are_not_skipped(page: Page, web_url: str) -> None:
    from httpx import AsyncClient

    await sign_in(page, web_url)
    message, send = parts(page)
    await message.fill("медленно: " + QUESTION)
    await send.click()
    await expect(page.get_by_text("печатает…")).to_be_visible()
    async with AsyncClient(base_url=web_url, headers={"Origin": web_url}) as other:
        login = await other.post("/api/session", headers={"X-Access-Key": ACCESS_KEY})
        assert login.status_code == 204
        sent = await other.post("/api/messages", json={"text": "Вопрос другого гостя"})
        assert sent.status_code == 201
    await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    await expect(page.locator("#pending li")).to_have_count(0)
    await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    await expect(page.get_by_text("Вопрос другого гостя")).to_be_visible()
    await expect(page.locator("#messages li")).to_have_count(4)


@pytest.mark.anyio
async def test_text_survives_an_expired_session_during_send(page: Page, web_url: str) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)

    async def expire(route: Route) -> None:
        if route.request.method == "POST":
            await route.fulfill(status=401, json={"error": {"code": "unauthorized"}})
        else:
            await route.continue_()

    await page.route("**/api/messages", expire)
    await message.fill("Мой длинный вопрос про турку")
    await send.click()
    await expect(page.get_by_label("Ключ доступа")).to_be_visible()
    await page.unroute("**/api/messages")
    await page.get_by_label("Ключ доступа").fill(ACCESS_KEY)
    await page.get_by_role("button", name="Войти").click()
    await expect(message).to_have_value("Мой длинный вопрос про турку")
    assert "Мой длинный" not in await page.evaluate(
        "JSON.stringify(localStorage) + JSON.stringify(sessionStorage)"
    )


@pytest.mark.anyio
async def test_draft_survives_an_expired_session_seen_by_polling(page: Page, web_url: str) -> None:
    await sign_in(page, web_url)
    message, _ = parts(page)

    async def expire(route: Route) -> None:
        if route.request.method == "GET":
            await route.fulfill(status=401, json={"error": {"code": "unauthorized"}})
        else:
            await route.continue_()

    await message.fill("Черновик про аэропресс")
    await page.route("**/api/messages?*", expire)
    await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    await expect(page.get_by_label("Ключ доступа")).to_be_visible()
    await expect(message).to_have_value("")
    await page.unroute("**/api/messages?*")
    await page.get_by_label("Ключ доступа").fill(ACCESS_KEY)
    await page.get_by_role("button", name="Войти").click()
    await expect(message).to_have_value("Черновик про аэропресс")
    assert "Черновик" not in await page.evaluate(
        "JSON.stringify(localStorage) + JSON.stringify(sessionStorage)"
    )


@pytest.mark.anyio
async def test_follow_up_draft_and_sent_question_both_survive_expiry(
    page: Page, web_url: str
) -> None:
    await sign_in(page, web_url)
    message, send = parts(page)
    release = asyncio.Event()

    async def expire_later(route: Route) -> None:
        if route.request.method == "POST":
            await release.wait()
            await route.fulfill(status=401, json={"error": {"code": "unauthorized"}})
        else:
            await route.continue_()

    await page.route("**/api/messages", expire_later)
    await message.fill("Первый вопрос")
    await send.click()
    await expect(page.get_by_text("печатает…")).to_be_visible()
    await message.fill("Черновик продолжения")
    release.set()
    await expect(page.get_by_label("Ключ доступа")).to_be_visible()
    await page.unroute("**/api/messages")
    await page.get_by_label("Ключ доступа").fill(ACCESS_KEY)
    await page.get_by_role("button", name="Войти").click()
    await expect(message).to_have_value("Первый вопрос\n\nЧерновик продолжения")
    assert "Черновик" not in await page.evaluate(
        "JSON.stringify(localStorage) + JSON.stringify(sessionStorage)"
    )


@pytest.mark.anyio
async def test_earlier_question_answered_later_is_shown_above(page: Page, web_url: str) -> None:
    from httpx import AsyncClient

    await sign_in(page, web_url)
    message, send = parts(page)
    await message.fill("медленно: первый")
    await send.click()
    await expect(page.get_by_text("печатает…")).to_be_visible()
    async with AsyncClient(base_url=web_url, headers={"Origin": web_url}) as other:
        await other.post("/api/session", headers={"X-Access-Key": ACCESS_KEY})
        assert (await other.post("/api/messages", json={"text": "второй"})).status_code == 201
    await expect(page.locator("#pending li")).to_have_count(0)
    users = page.locator("#messages .message-body:not(.markdown)")
    await expect(users).to_have_text(["медленно: первый", "второй"])
    await page.reload()
    await expect(users).to_have_text(["медленно: первый", "второй"])
