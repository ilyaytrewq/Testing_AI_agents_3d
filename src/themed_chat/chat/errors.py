class GenerationError(RuntimeError):
    """The model did not produce a usable response."""


class GenerationTimeout(GenerationError):
    """The model took too long to respond."""


class EmptyCompletion(GenerationError):
    """The provider answered, but with no text (for example cut off at max_tokens)."""


class StorageUnavailable(RuntimeError):
    """The chat storage could not be reached or failed; the request can be retried later."""
