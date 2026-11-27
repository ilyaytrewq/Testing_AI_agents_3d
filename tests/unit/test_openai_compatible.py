import json
from asyncio import sleep
from importlib.util import find_spec

import pytest
from httpx import AsyncClient, MockTransport, Request, Response
from openai import AsyncOpenAI

from themed_chat.chat.service import GenerationError, GenerationTimeout
from themed_chat.settings import ModelSettings

BASE = "https://qwen.test/compatible-mode/v1"


def settings(timeout_seconds: float = 1) -> ModelSettings:
    return ModelSettings(
        provider="openai_compatible",
        base_url=BASE,
        model="qwen-plus",
        system_prompt="Coffee only",
        max_output_tokens=128,
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.anyio
async def test_sdk_sends_qwen_model_prompt_and_access_token() -> None:
    assert find_spec("themed_chat.adapters.openai_compatible") is not None, "Adapter is missing"
    from themed_chat.adapters.openai_compatible import OpenAICompatibleGenerator

    def reply(request: Request) -> Response:
        assert request.method == "POST"
        assert str(request.url) == BASE + "/chat/completions"
        assert request.headers["authorization"] == "Bearer qwen-fixture"
        assert json.loads(request.content) == {
            "model": "qwen-plus",
            "max_tokens": 128,
            "messages": [
                {"role": "system", "content": "Coffee only"},
                {"role": "user", "content": "How should I brew?"},
            ],
        }
        return Response(200, json={"choices": [{"message": {"content": "Try a filter."}}]})

    async with AsyncOpenAI(
        api_key="qwen-fixture",
        base_url=BASE,
        max_retries=0,
        http_client=AsyncClient(transport=MockTransport(reply)),
    ) as client:
        generator = OpenAICompatibleGenerator(client, settings())
        assert await generator.generate("How should I brew?") == "Try a filter."


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (429, {"error": {"message": "private-marker"}}),
        (200, {"choices": 123}),
        (200, {"choices": []}),
        (200, {"choices": [{"message": {"content": "  "}}]}),
        (200, {"choices": [{"message": {"content": [123]}}]}),
    ],
)
async def test_bad_replies_map_to_safe_generation_error(status: int, payload: object) -> None:
    from themed_chat.adapters.openai_compatible import OpenAICompatibleGenerator

    async with AsyncOpenAI(
        api_key="fixture",
        base_url=BASE,
        max_retries=0,
        http_client=AsyncClient(transport=MockTransport(lambda _: Response(status, json=payload))),
    ) as client:
        with pytest.raises(GenerationError) as failure:
            await OpenAICompatibleGenerator(client, settings()).generate("test")
        assert "private-marker" not in str(failure.value)
        assert failure.value.__suppress_context__ or failure.value.__context__ is None


@pytest.mark.anyio
async def test_compatible_call_has_an_overall_deadline() -> None:
    from themed_chat.adapters.openai_compatible import OpenAICompatibleGenerator

    async def reply(_: Request) -> Response:
        await sleep(5)
        return Response(500)

    async with AsyncOpenAI(
        api_key="fixture",
        base_url=BASE,
        max_retries=0,
        http_client=AsyncClient(transport=MockTransport(reply)),
    ) as client:
        with pytest.raises(GenerationTimeout):
            await OpenAICompatibleGenerator(client, settings(0.02)).generate("test")


@pytest.mark.anyio
async def test_connection_does_not_forward_ambient_openai_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import SecretStr

    from themed_chat.adapters.openai_compatible import connect_openai_compatible

    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "authorization: Bearer ambient\nX-Private: private")
    monkeypatch.setenv("OPENAI_ORG_ID", "ambient-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "ambient-project")

    def reply(request: Request) -> Response:
        assert request.headers.get_list("authorization") == ["Bearer selected"]
        assert not {"x-private", "openai-organization", "openai-project"} & request.headers.keys()
        return Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    http = AsyncClient(transport=MockTransport(reply))
    monkeypatch.setattr("themed_chat.adapters.openai_compatible.AsyncClient", lambda **_: http)
    async with connect_openai_compatible(settings(), SecretStr("selected")) as generator:
        assert await generator.generate("test") == "OK"
