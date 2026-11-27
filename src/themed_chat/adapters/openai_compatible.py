from asyncio import timeout
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import AsyncClient
from openai import APIError, APITimeoutError, AsyncOpenAI, Omit
from pydantic import SecretStr

from themed_chat.chat.service import GenerationError, GenerationTimeout
from themed_chat.settings import ModelSettings


class _CompatibleClient(AsyncOpenAI):
    @property
    def default_headers(self) -> dict[str, str | Omit]:
        # The SDK otherwise imports ambient OpenAI headers, including credentials.
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **self.auth_headers,
        }


class OpenAICompatibleGenerator:
    def __init__(self, client: AsyncOpenAI, settings: ModelSettings) -> None:
        self.client = client
        self.settings = settings

    async def generate(self, text: str) -> str:
        try:
            async with timeout(self.settings.timeout_seconds):
                response = await self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=[
                        {"role": "system", "content": self.settings.system_prompt},
                        {"role": "user", "content": text},
                    ],
                    max_tokens=self.settings.max_output_tokens,
                )
                answer = response.choices[0].message.content
        except (TimeoutError, APITimeoutError):
            raise GenerationTimeout("The provider exceeded its deadline.") from None
        except (APIError, AttributeError, IndexError, KeyError, TypeError, ValueError):
            raise GenerationError("The provider could not generate a response.") from None
        if not isinstance(answer, str) or not answer.strip():
            raise GenerationError("The provider returned no text.")
        return answer


@asynccontextmanager
async def connect_openai_compatible(
    settings: ModelSettings, key: SecretStr
) -> AsyncIterator[OpenAICompatibleGenerator]:
    async with (
        AsyncClient(follow_redirects=False, timeout=settings.timeout_seconds) as http,
        _CompatibleClient(
            api_key=key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
            http_client=http,
        ) as client,
    ):
        yield OpenAICompatibleGenerator(client, settings)
