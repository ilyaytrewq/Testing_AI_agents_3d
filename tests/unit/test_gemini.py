import json
from importlib.util import find_spec

import pytest
from google import genai
from google.genai import types
from httpx import AsyncClient, MockTransport, Request, Response

from themed_chat.chat.service import GenerationError, GenerationTimeout
from themed_chat.settings import ModelSettings


@pytest.mark.anyio
async def test_configured_model_and_system_prompt_reach_google_sdk() -> None:
    assert find_spec("themed_chat.adapters.gemini") is not None, "Gemini adapter is missing"
    from themed_chat.adapters.gemini import GeminiGenerator

    def respond(request: Request) -> Response:
        body = json.loads(request.content)
        assert request.url.path.endswith("/models/fixture-model:generateContent")
        assert body["systemInstruction"]["parts"] == [{"text": "System instruction"}]
        assert body["contents"] == [{"parts": [{"text": "User text"}], "role": "user"}]
        assert body["generationConfig"]["maxOutputTokens"] == 256
        return Response(
            200,
            json={
                "candidates": [{"content": {"role": "model", "parts": [{"text": "Model reply"}]}}]
            },
        )

    async with AsyncClient(transport=MockTransport(respond)) as http:
        with genai.Client(
            vertexai=False,
            api_key="fixture-key",
            http_options=types.HttpOptions(httpx_async_client=http),
        ) as sdk:
            async with sdk.aio as client:
                generator = GeminiGenerator(
                    client,
                    ModelSettings(
                        model="fixture-model",
                        system_prompt="System instruction",
                        max_output_tokens=256,
                    ),
                )
                assert await generator.generate("User text") == "Model reply"


@pytest.mark.anyio
async def test_provider_errors_do_not_expose_provider_details() -> None:
    from themed_chat.adapters.gemini import GeminiGenerator

    def respond(_request: Request) -> Response:
        return Response(
            429,
            json={
                "error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "private detail"}
            },
        )

    async with AsyncClient(transport=MockTransport(respond)) as http:
        with genai.Client(
            vertexai=False,
            api_key="fixture-key",
            http_options=types.HttpOptions(
                httpx_async_client=http, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        ) as sdk:
            async with sdk.aio as client:
                generator = GeminiGenerator(
                    client, ModelSettings(model="test", system_prompt="test")
                )
                with pytest.raises(
                    GenerationError, match="The provider could not generate"
                ) as caught:
                    await generator.generate("Coffee")
                assert "private detail" not in str(caught.value)


@pytest.mark.anyio
async def test_provider_request_has_an_overall_deadline() -> None:
    from asyncio import sleep

    from themed_chat.adapters.gemini import GeminiGenerator

    async def respond(_request: Request) -> Response:
        await sleep(10)
        return Response(500)

    async with AsyncClient(transport=MockTransport(respond)) as http:
        with genai.Client(
            vertexai=False,
            api_key="fixture-key",
            http_options=types.HttpOptions(httpx_async_client=http),
        ) as sdk:
            async with sdk.aio as client:
                generator = GeminiGenerator(
                    client, ModelSettings(model="test", system_prompt="test", timeout_seconds=0.02)
                )
                with pytest.raises(GenerationTimeout):
                    await generator.generate("Coffee")
