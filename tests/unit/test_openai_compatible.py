import json
import logging
from asyncio import sleep

import pytest
from httpx import AsyncClient, ConnectError, MockTransport, Request, Response
from pydantic import SecretStr

from themed_chat.adapters.openai_compatible import (
    OpenAICompatibleGenerator,
    connect_openai_compatible,
)
from themed_chat.chat.service import GenerationError, GenerationTimeout
from themed_chat.settings import ModelSettings

BASE = "https://qwen.test/compatible-mode/v1"
KEY = "fixture-token-1234"


def settings(timeout_seconds: float = 5) -> ModelSettings:
    return ModelSettings(
        base_url=BASE,
        model="qwen-plus",
        system_prompt="Coffee only",
        max_output_tokens=128,
        timeout_seconds=timeout_seconds,
    )


def generator(handler: object, timeout_seconds: float = 5) -> OpenAICompatibleGenerator:
    client = AsyncClient(transport=MockTransport(handler))  # type: ignore[arg-type]
    return OpenAICompatibleGenerator(client, settings(timeout_seconds), SecretStr(KEY))


@pytest.mark.anyio
async def test_sends_model_prompt_and_bearer_token_to_chat_completions() -> None:
    def reply(request: Request) -> Response:
        assert request.method == "POST"
        assert str(request.url) == BASE + "/chat/completions"
        assert request.headers.get_list("authorization") == [f"Bearer {KEY}"]
        assert request.headers["content-type"] == "application/json"
        assert request.headers["accept"] == "application/json"
        assert json.loads(request.content) == {
            "model": "qwen-plus",
            "messages": [
                {"role": "system", "content": "Coffee only"},
                {
                    "role": "user",
                    "content": "<user_question>\nHow should I brew?\n</user_question>",
                },
            ],
            "max_tokens": 128,
        }
        return Response(200, json={"choices": [{"message": {"content": "Try a filter."}}]})

    assert await generator(reply).generate("How should I brew?") == "Try a filter."


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (429, {"error": {"message": "private-marker"}}),
        (500, "private-marker"),
        (200, {"choices": 123}),
        (200, {"choices": []}),
        (200, {"choices": [None]}),
        (200, {"choices": [{"message": None}]}),
        (200, {"choices": [{"message": {"content": "  "}}]}),
        (200, {"choices": [{"message": {"content": None}}]}),
        (200, {"choices": [{"message": {"content": [123]}}]}),
        (200, ["choices"]),
        (200, "private-marker"),
    ],
)
async def test_bad_replies_map_to_safe_generation_error(status: int, payload: object) -> None:
    with pytest.raises(GenerationError) as failure:
        await generator(lambda _: Response(status, json=payload)).generate("test")
    assert not isinstance(failure.value, GenerationTimeout)
    assert "private-marker" not in str(failure.value)
    assert failure.value.__suppress_context__ or failure.value.__context__ is None


@pytest.mark.anyio
async def test_unreadable_body_is_a_generation_error() -> None:
    with pytest.raises(GenerationError):
        await generator(lambda _: Response(200, content=b"<html>")).generate("test")


@pytest.mark.anyio
async def test_connection_failure_is_a_generation_error() -> None:
    def refuse(request: Request) -> Response:
        raise ConnectError("private-marker", request=request)

    with pytest.raises(GenerationError) as failure:
        await generator(refuse).generate("test")
    assert "private-marker" not in str(failure.value)


@pytest.mark.anyio
async def test_call_has_an_overall_deadline() -> None:
    async def reply(_: Request) -> Response:
        await sleep(5)
        return Response(500)

    with pytest.raises(GenerationTimeout):
        await generator(reply, 0.02).generate("test")


@pytest.mark.anyio
async def test_redirects_are_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    options: dict[str, object] = {}

    def reply(request: Request) -> Response:
        seen.append(str(request.url))
        return Response(302, headers={"Location": "https://elsewhere.test/steal"})

    def factory(**kwargs: object) -> AsyncClient:
        options.update(kwargs)
        return AsyncClient(transport=MockTransport(reply), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("themed_chat.adapters.openai_compatible.AsyncClient", factory)
    async with connect_openai_compatible(settings(7), SecretStr(KEY)) as client:
        with pytest.raises(GenerationError):
            await client.generate("test")
    assert seen == [BASE + "/chat/completions"]
    assert options["follow_redirects"] is False
    assert options["trust_env"] is False  # No proxy from HTTPS_PROXY and the like.
    assert options["timeout"] == 7  # Not shorter than the overall deadline.


@pytest.mark.anyio
async def test_connection_does_not_use_ambient_openai_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "authorization: Bearer ambient\nX-Private: private")
    monkeypatch.setenv("OPENAI_ORG_ID", "ambient-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "ambient-project")

    def reply(request: Request) -> Response:
        assert request.headers.get_list("authorization") == ["Bearer selected"]
        assert not {"x-private", "openai-organization", "openai-project"} & request.headers.keys()
        return Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    http = AsyncClient(transport=MockTransport(reply))
    monkeypatch.setattr("themed_chat.adapters.openai_compatible.AsyncClient", lambda **_: http)
    async with connect_openai_compatible(settings(), SecretStr("selected")) as client:
        assert await client.generate("test") == "OK"
    assert http.is_closed


@pytest.mark.anyio
async def test_failures_are_logged_without_secrets_or_message_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = {"error": {"type": "rate_limit_exceeded", "message": "private-marker"}}
    caplog.set_level(logging.INFO)
    with pytest.raises(GenerationError):
        await generator(lambda _: Response(429, json=body)).generate("secret question")
    with pytest.raises(GenerationError):
        await generator(lambda _: Response(200, json={"choices": []})).generate("secret question")

    def refuse(request: Request) -> Response:
        raise ConnectError("private-marker", request=request)

    with pytest.raises(GenerationError):
        await generator(refuse).generate("secret question")
    log = caplog.text
    assert "status=429" in log and "rate_limit_exceeded" in log and "ConnectError" in log
    for private in (KEY, "private-marker", "secret question", "Authorization"):
        assert private not in log


@pytest.mark.anyio
async def test_raw_os_error_is_a_generation_error() -> None:
    def reset(_: Request) -> Response:
        raise ConnectionResetError("private-marker")

    with pytest.raises(GenerationError) as failure:
        await generator(reset).generate("test")
    assert not isinstance(failure.value, GenerationTimeout)
    assert "private-marker" not in str(failure.value)


@pytest.mark.anyio
@pytest.mark.parametrize("content", [None, "", "  "])
async def test_truncated_reply_without_content_is_an_empty_completion(
    content: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    from themed_chat.chat.errors import EmptyCompletion

    body = {"choices": [{"message": {"content": content}, "finish_reason": "length"}]}
    with pytest.raises(EmptyCompletion):
        await generator(lambda _: Response(200, json=body)).generate("secret question")
    assert "truncated before any content" in caplog.text
    assert "secret question" not in caplog.text


@pytest.mark.anyio
async def test_truncated_reply_with_content_is_accepted_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = {"choices": [{"message": {"content": "Half an answer"}, "finish_reason": "length"}]}
    from themed_chat.chat.models import TruncatedText

    answer = await generator(lambda _: Response(200, json=body)).generate("q")
    assert answer == "Half an answer" and isinstance(answer, TruncatedText)
    assert "truncated at max_tokens=128" in caplog.text
    assert "Half an answer" not in caplog.text


@pytest.mark.anyio
async def test_response_format_is_sent_when_requested() -> None:
    seen: list[dict[str, object]] = []

    def reply(request: Request) -> Response:
        seen.append(json.loads(request.content))
        return Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    await generator(reply).complete("s", "u", 64, response_format={"type": "json_object"})
    await generator(reply).complete("s", "u", 64)
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in seen[1]


def test_main_model_default_budget_leaves_room_for_reasoning() -> None:
    assert ModelSettings(base_url=BASE, model="m", system_prompt="p").max_output_tokens == 4096
