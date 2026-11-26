from asyncio import timeout
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from math import ceil

from google import genai
from google.genai import errors, types
from google.genai.client import AsyncClient
from httpx import HTTPError, TimeoutException
from pydantic import SecretStr

from themed_chat.chat.service import GenerationError, GenerationTimeout
from themed_chat.settings import ModelSettings


class GeminiGenerator:
    def __init__(self, client: AsyncClient, settings: ModelSettings) -> None:
        self.client = client
        self.settings = settings

    async def generate(self, text: str) -> str:
        try:
            async with timeout(self.settings.timeout_seconds):
                response = await self.client.models.generate_content(
                    model=self.settings.model,
                    contents=text,
                    config=types.GenerateContentConfig(
                        system_instruction=self.settings.system_prompt,
                        max_output_tokens=self.settings.max_output_tokens,
                    ),
                )
                answer = response.text
        except (TimeoutError, TimeoutException):
            raise GenerationTimeout("The provider exceeded its deadline.") from None
        except (errors.APIError, HTTPError, ValueError):
            raise GenerationError("The provider could not generate a response.") from None
        if not answer:
            raise GenerationError("The provider returned no text.")
        return answer


@asynccontextmanager
async def connect_gemini(settings: ModelSettings, key: SecretStr) -> AsyncIterator[GeminiGenerator]:
    options = types.HttpOptions(
        timeout=ceil(settings.timeout_seconds * 1000),
        retry_options=types.HttpRetryOptions(attempts=1),
    )
    with genai.Client(vertexai=False, api_key=key.get_secret_value(), http_options=options) as sdk:
        async with sdk.aio as client:
            yield GeminiGenerator(client, settings)
