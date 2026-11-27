"""Model providers by name (llm.provider). Adding one: a module with a connect function
that yields a ModelClient, plus one line in PROVIDERS."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from pydantic import SecretStr

from themed_chat.adapters.openai_compatible import connect_openai_compatible
from themed_chat.chat.ports import ModelClient
from themed_chat.settings import ConfigurationError, ModelSettings


class ConnectModel(Protocol):
    def __call__(
        self, settings: ModelSettings, key: SecretStr, *, temperature: float | None = None
    ) -> AbstractAsyncContextManager[ModelClient]:
        """Open a client for the duration of the context; temperature None: provider default."""
        ...


PROVIDERS: dict[str, ConnectModel] = {
    "openai_compatible": connect_openai_compatible,
}


def connect_function(name: str) -> ConnectModel:
    try:
        return PROVIDERS[name]
    except KeyError:
        known = ", ".join(sorted(PROVIDERS))
        raise ConfigurationError(f"Unknown llm.provider; use one of: {known}.") from None
