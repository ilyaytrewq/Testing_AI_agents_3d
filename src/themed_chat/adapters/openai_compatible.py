import logging
from asyncio import timeout
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from re import compile as compile_pattern

from httpx import AsyncClient, HTTPError, Response, TimeoutException
from pydantic import SecretStr

from themed_chat.chat.errors import EmptyCompletion, GenerationError, GenerationTimeout
from themed_chat.chat.guard import wrap_question
from themed_chat.chat.models import TruncatedText
from themed_chat.settings import ModelSettings

logger = logging.getLogger(__name__)

# Provider error labels worth logging ("rate_limit_exceeded", "RESOURCE_EXHAUSTED", ...).
SAFE_LABEL = compile_pattern(r"[A-Za-z0-9_.-]{1,64}")


def _provider_error_label(response: Response) -> str:
    """Return the provider's short error type or status, never its message."""
    try:
        payload = response.json()
    except ValueError:
        return "unknown"
    if isinstance(payload, list) and payload:
        payload = payload[0]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        for field in ("type", "status", "code"):
            value = error.get(field)
            if isinstance(value, str | int) and SAFE_LABEL.fullmatch(str(value)):
                return str(value)
    return "unknown"


@dataclass(frozen=True, slots=True)
class Choice:
    content: str | None  # None: missing, null or blank
    finish_reason: str | None


def _choice(payload: object) -> Choice | None:
    """Return choices[0] if the payload has the chat completion shape, else None."""
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        return None
    reason = choices[0].get("finish_reason")
    return Choice(
        content if content is not None and content.strip() else None,
        reason if isinstance(reason, str) else None,
    )


def _label(choice: Choice) -> str:
    reason = choice.finish_reason
    return reason if reason is not None and SAFE_LABEL.fullmatch(reason) else "unknown"


class OpenAICompatibleGenerator:
    """Calls POST {base_url}/chat/completions of any OpenAI-compatible API."""

    def __init__(
        self,
        client: AsyncClient,
        settings: ModelSettings,
        api_key: SecretStr,
        *,
        temperature: float | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.api_key = api_key
        self.temperature = temperature
        self.url = f"{settings.base_url}/chat/completions"
        # Only these headers are sent: nothing comes from the environment.
        self.headers = {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def generate(self, text: str) -> str:
        # The question is data inside markup, never instructions (see the system prompt).
        return await self.complete(
            self.settings.system_prompt, wrap_question(text), self.settings.max_output_tokens
        )

    async def complete(
        self,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
        *,
        response_format: Mapping[str, object] | None = None,
    ) -> str:
        body: dict[str, object] = {
            **self.settings.extra_body,
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": max_tokens,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if response_format is not None:
            body["response_format"] = dict(response_format)
        try:
            async with timeout(self.settings.timeout_seconds):
                response = await self.client.post(self.url, headers=self.headers, json=body)
        except (TimeoutError, TimeoutException) as error:
            logger.warning("LLM request timed out: %s", type(error).__name__)
            raise GenerationTimeout("The provider exceeded its deadline.") from None
        except (HTTPError, OSError) as error:
            # A transport can also let a raw OSError (reset, TLS failure) escape httpx.
            # httpx error messages can echo the URL, so only the class is logged.
            logger.warning("LLM transport failure: %s", type(error).__name__)
            raise GenerationError("The provider could not be reached.") from None
        if not response.is_success:
            logger.warning(
                "LLM request failed: status=%s provider_error=%s",
                response.status_code,
                _provider_error_label(response),
            )
            raise GenerationError("The provider rejected the request.")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        choice = _choice(payload)
        if choice is None:
            logger.warning("LLM response has an unexpected shape: status=%s", response.status_code)
            raise GenerationError("The provider returned no text.")
        truncated = choice.finish_reason == "length"
        if choice.content is None:
            if truncated:
                # Reasoning models can spend all of max_tokens before writing any content.
                logger.warning(
                    "LLM reply was truncated before any content: max_tokens=%s", max_tokens
                )
            else:
                logger.warning("LLM reply has no content: finish_reason=%s", _label(choice))
            raise EmptyCompletion("The provider returned no text.")
        if truncated:
            logger.warning("LLM reply was truncated at max_tokens=%s.", max_tokens)
            return TruncatedText(choice.content)
        return choice.content


@asynccontextmanager
async def connect_openai_compatible(
    settings: ModelSettings, key: SecretStr, *, temperature: float | None = None
) -> AsyncIterator[OpenAICompatibleGenerator]:
    # trust_env=False: no proxy, netrc or certificate settings from the environment,
    # so the request carrying the key goes only where base_url points.
    async with AsyncClient(
        follow_redirects=False, timeout=settings.timeout_seconds, trust_env=False
    ) as client:
        yield OpenAICompatibleGenerator(client, settings, key, temperature=temperature)
