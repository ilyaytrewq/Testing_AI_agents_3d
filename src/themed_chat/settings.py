from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_network
from json import dumps, loads
from os import environ
from pathlib import Path
from re import compile as compile_pattern
from typing import Annotated, Self
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from yaml import YAMLError, safe_load

ACCESS_KEY_PATTERN = compile_pattern(r"[A-Za-z0-9_-]{8,255}")
DEFAULT_CONFIG_FILE = Path("config/app.yaml")
CONFIG_FILE_ENV = "APP_CONFIG_FILE"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ConfigurationError(RuntimeError):
    """Operator-facing error that never contains a raw settings value."""


class ConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class ChatSettings(ConfigSection):
    title: NonBlank = "Кофейный бариста"
    # Per guest: protects the model quota from a runaway client.
    message_limit: Annotated[int, Field(ge=1, le=1000)] = 10
    message_window_seconds: Annotated[int, Field(ge=1, le=86400)] = 60


def _json_mapping(value: object) -> object:
    """Environment overrides arrive as strings: accept a JSON object there."""
    if isinstance(value, str):
        try:
            return loads(value) if value.strip() else {}
        except ValueError:
            raise ValueError("use a JSON object") from None
    return value


# Extra request fields must not replace what the client itself sends.
RESERVED_BODY_FIELDS = frozenset({"model", "messages", "max_tokens", "stream", "response_format"})


def _check_extra_body(value: dict[str, object]) -> dict[str, object]:
    if RESERVED_BODY_FIELDS & value.keys():
        raise ValueError(
            "extra_body must not set model, messages, max_tokens, stream or response_format"
        )
    try:
        # It is sent as JSON: reject YAML dates, NaN and the like here, not on the first request.
        dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("extra_body must contain only JSON values") from None
    return value


ExtraBody = Annotated[
    dict[str, object], BeforeValidator(_json_mapping), AfterValidator(_check_extra_body)
]


def _validate_base_url(value: str) -> str:
    if any(char.isspace() or char in "\\?#" for char in value):
        raise ValueError("use a base URL without whitespace, a query, or a fragment")
    url = AnyHttpUrl(value)
    if url.username is not None or url.password is not None or not url.host:
        raise ValueError("use an absolute HTTP(S) URL without credentials")
    if url.scheme == "http" and url.host not in LOOPBACK_HOSTS:
        raise ValueError("HTTPS is required outside loopback hosts")
    canonical = str(url).rstrip("/")
    if canonical.endswith("/chat/completions"):
        raise ValueError("specify the API base, not the chat completions endpoint")
    return canonical


DEFAULT_PORTS = {"http": 80, "https": 443}


def url_origin(url: str) -> tuple[str, str, int | None]:
    """Scheme, host and port: where a request with a key actually goes."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or DEFAULT_PORTS.get(scheme)


class ModelSettings(ConfigSection):
    # A name from themed_chat.adapters.providers.PROVIDERS.
    provider: NonBlank = "openai_compatible"
    base_url: str
    model: NonBlank
    system_prompt: NonBlank
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 25.0
    # Reasoning models count their reasoning against this limit too.
    max_output_tokens: Annotated[int, Field(gt=0, le=8192)] = 4096
    # Provider-specific request fields, e.g. {"reasoning_effort": "low"}.
    extra_body: ExtraBody = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validate_base_url(value)


def _network_list(value: object) -> object:
    """A JSON list or a comma-separated string from the environment, as strict networks."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                value = loads(stripped)
            except ValueError:
                raise ValueError("use a JSON list of CIDR ranges") from None
        else:
            value = [part for part in stripped.split(",") if part.strip()]
    if not isinstance(value, list | tuple):
        raise ValueError("use a list of CIDR ranges")
    networks: list[IPv4Network | IPv6Network] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("use CIDR ranges such as 10.0.0.0/8")
        networks.append(ip_network(item.strip(), strict=True))
    return tuple(networks)


TrustedProxies = Annotated[tuple[IPv4Network | IPv6Network, ...], BeforeValidator(_network_list)]


class AuthSettings(ConfigSection):
    public_origin: str = "http://127.0.0.1:8000"
    session_ttl_seconds: Annotated[int, Field(ge=1, le=604800)] = 28800
    # Per client address: slows down guessing of the access key.
    login_attempts: Annotated[int, Field(ge=1, le=1000)] = 10
    login_window_seconds: Annotated[int, Field(ge=1, le=86400)] = 60
    # Proxies whose X-Forwarded-For is believed; empty: the TCP peer is the client.
    trusted_proxies: TrustedProxies = ()

    @property
    def cookie_secure(self) -> bool:
        return self.public_origin.startswith("https://")

    @field_validator("public_origin")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        url = urlsplit(value)
        host = url.hostname
        if (
            not host
            or value != f"{url.scheme}://{url.netloc}"
            or url.username is not None
            or url.scheme not in {"http", "https"}
            or any(char.isspace() or char in "\\%" for char in host)
        ):
            raise ValueError("use a scheme and host with no path, credentials, or query")
        canonical = AnyHttpUrl(value)
        if canonical.scheme == "http" and canonical.host not in LOOPBACK_HOSTS:
            raise ValueError("HTTPS is required outside loopback hosts")
        return str(canonical).removesuffix("/")


LANGUAGE_CODE = compile_pattern(r"[a-z]{2}")
REQUIRED_REFUSAL_LANGUAGES = frozenset({"ru", "en", "de", "uk", "zh", "es", "fr"})
DEFAULT_REFUSALS = {
    "ru": "Я помогаю только с вопросами о кофе: зёрна, помол, пропорции, способы заваривания "
    "и оборудование. Спросите, например, как заварить кофе в турке или в воронке.",
    "en": "I can only help with coffee: beans, grinding, ratios, brewing methods and "
    "equipment. Try asking, for example, how to brew coffee with a pour-over.",
    "de": "Ich helfe nur bei Fragen rund um Kaffee: Bohnen, Mahlgrad, Mengenverhältnis, "
    "Zubereitung und Ausrüstung. Fragen Sie zum Beispiel, wie man Kaffee im Handfilter "
    "zubereitet.",
    "uk": "Я допомагаю лише з питаннями про каву: зерна, помел, пропорції, способи "
    "заварювання та обладнання. Запитайте, наприклад, як заварити каву в турці.",
    "zh": "我只能回答与咖啡有关的问题：咖啡豆、研磨、粉水比、冲煮方法和器具。"
    "比如，您可以问问如何用手冲壶冲咖啡。",
    "es": "Solo puedo ayudar con preguntas sobre café: granos, molienda, proporciones, "
    "métodos de preparación y equipo. Pregunte, por ejemplo, cómo preparar café de filtro.",
    "fr": "Je ne peux répondre qu'aux questions sur le café : grains, mouture, proportions, "
    "méthodes d'infusion et matériel. Demandez par exemple comment préparer un café filtre.",
}


class GuardSettings(ConfigSection):
    """Topic guard: an LLM classifier checks the question and then the answer."""

    enabled: bool = True
    # The refusal in the language the classifier detects (ISO 639-1), else the default.
    refusals: Annotated[dict[str, NonBlank], BeforeValidator(_json_mapping)] = Field(
        default_factory=lambda: dict(DEFAULT_REFUSALS)
    )
    # The UI is Russian: a refusal without a detected language is in Russian.
    default_refusal_language: NonBlank = "ru"
    # None: the classifier uses llm.model and llm.base_url (with LLM_API_KEY).
    classifier_model: str | None = None
    classifier_base_url: str | None = None
    classifier_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 10.0
    # Reasoning models spend part of max_tokens on thinking before the label.
    classifier_max_tokens: Annotated[int, Field(ge=1, le=4096)] = 1024
    # Ask for a JSON verdict via response_format (json_schema, strict). Turn off for
    # providers without json_schema support: the classifier then replies "LABEL lang".
    structured_output: bool = True
    # This many classifier replies in a row without a verdict count as an outage (502)
    # instead of off-topic refusals, so a broken provider is noticed.
    no_verdict_outage_threshold: Annotated[int, Field(ge=1, le=1000)] = 3
    classifier_extra_body: ExtraBody = Field(default_factory=dict)

    @field_validator("classifier_model", "classifier_base_url")
    @classmethod
    def blank_means_default(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("classifier_base_url")
    @classmethod
    def validate_classifier_base_url(cls, value: str | None) -> str | None:
        return _validate_base_url(value) if value is not None else None

    @field_validator("refusals")
    @classmethod
    def validate_refusals(cls, value: dict[str, str]) -> dict[str, str]:
        if any(LANGUAGE_CODE.fullmatch(code) is None for code in value):
            raise ValueError("use two-letter lowercase ISO 639-1 codes as keys")
        missing = REQUIRED_REFUSAL_LANGUAGES - value.keys()
        if missing:
            raise ValueError(f"add refusals for: {', '.join(sorted(missing))}")
        return value

    @model_validator(mode="after")
    def default_language_has_a_refusal(self) -> Self:
        if self.default_refusal_language not in self.refusals:
            raise ValueError("default_refusal_language must be one of the refusals")
        return self


class AppSettings(ConfigSection):
    chat: ChatSettings = ChatSettings()
    llm: ModelSettings
    auth: AuthSettings = AuthSettings()
    guard: GuardSettings = GuardSettings()


APP_SECTIONS: dict[str, type[ConfigSection]] = {
    "chat": ChatSettings,
    "llm": ModelSettings,
    "auth": AuthSettings,
    "guard": GuardSettings,
}


def _apply_environment_overrides(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or any(
        not isinstance(name, str) or name not in APP_SECTIONS for name in raw
    ):
        raise ValueError("expected a mapping of application sections")
    values: dict[str, object] = dict(raw)
    for section, schema in APP_SECTIONS.items():
        previous = values.get(section, {})
        if not isinstance(previous, dict):
            raise ValueError("expected each application section to be a mapping")
        overrides: dict[str, str] = {}
        for field_name in schema.model_fields:
            env_name = f"APP_{section.upper()}__{field_name.upper()}"
            if env_name in environ:
                overrides[field_name] = environ[env_name]
        if overrides:
            values[section] = {**previous, **overrides}
    return values


SECRET_NAMES = (
    "APP_ACCESS_KEY",
    "APP_SESSION_SECRET",
    "LLM_API_KEY",
    "CLASSIFIER_API_KEY",
    "DATABASE_URL",
)


class SecretSettings(ConfigSection):
    access_key: SecretStr = Field(validation_alias="APP_ACCESS_KEY")
    session_secret: SecretStr = Field(validation_alias="APP_SESSION_SECRET")
    llm_api_key: SecretStr = Field(validation_alias="LLM_API_KEY")
    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    # Only for a classifier on another host (guard.classifier_base_url).
    classifier_api_key: SecretStr | None = Field(
        default=None, validation_alias="CLASSIFIER_API_KEY"
    )

    @field_validator("access_key")
    @classmethod
    def validate_access_key(cls, value: SecretStr) -> SecretStr:
        if ACCESS_KEY_PATTERN.fullmatch(value.get_secret_value()) is None:
            raise ValueError("use 8–255 ASCII letters, digits, hyphens or underscores")
        return value

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().strip()) < 32:
            raise ValueError("use at least 32 characters")
        return value

    @field_validator("database_url", "llm_api_key", "classifier_api_key")
    @classmethod
    def validate_nonblank_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("the value must not be blank")
        return value

    @model_validator(mode="after")
    def validate_independent_keys(self) -> Self:
        if self.access_key == self.session_secret:
            raise ValueError("the access key and session signing secret must differ")
        return self


@dataclass(frozen=True, slots=True)
class Settings:
    app: AppSettings
    secrets: SecretSettings

    def __post_init__(self) -> None:
        # The main key must never be sent to another host.
        if self.classifier_on_other_host and self.secrets.classifier_api_key is None:
            raise ConfigurationError(
                "guard.classifier_base_url points to another origin: set CLASSIFIER_API_KEY."
            )

    @property
    def classifier_on_other_host(self) -> bool:
        base_url = self.app.guard.classifier_base_url
        return base_url is not None and url_origin(base_url) != url_origin(self.app.llm.base_url)

    @property
    def classifier_model_settings(self) -> ModelSettings:
        """The main model settings with the classifier's endpoint, model and limits."""
        guard, llm = self.app.guard, self.app.llm
        return llm.model_copy(
            update={
                "base_url": guard.classifier_base_url or llm.base_url,
                "model": guard.classifier_model or llm.model,
                "timeout_seconds": guard.classifier_timeout_seconds,
                "extra_body": dict(guard.classifier_extra_body),
            }
        )

    @property
    def classifier_api_key(self) -> SecretStr:
        """The key for the classifier's API: its own if configured, else the main one."""
        if self.app.guard.classifier_base_url is not None and self.secrets.classifier_api_key:
            return self.secrets.classifier_api_key
        return self.secrets.llm_api_key


def load_app_settings(config_file: Path | None = None) -> AppSettings:
    """Read the YAML file and apply APP_<SECTION>__<FIELD> overrides; no secrets."""
    if config_file is None:
        config_file = Path(environ.get(CONFIG_FILE_ENV) or DEFAULT_CONFIG_FILE)
    try:
        if not config_file.is_file():
            raise ConfigurationError("Application YAML configuration file was not found.")
        yaml_values: object = safe_load(config_file.read_text(encoding="utf-8"))
        return AppSettings.model_validate(_apply_environment_overrides(yaml_values))
    except (OSError, ValueError, YAMLError):
        raise ConfigurationError(
            "Invalid application configuration. Check the YAML file and APP_ overrides."
        ) from None


def _read_secret_file(name: str, path: str) -> str:
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise ConfigurationError(f"Could not read the file named by {name}_FILE.") from None
    # Editors and `kubectl create secret --from-file` often add one final newline.
    return content.removesuffix("\n").removesuffix("\r")


def _secret_values(file_values: dict[str, str | None]) -> dict[str, str]:
    """NAME from the environment or .env, or the content of the file named by NAME_FILE."""
    values: dict[str, str] = {}
    for name in SECRET_NAMES:
        direct = environ.get(name, file_values.get(name))
        path = environ.get(f"{name}_FILE", file_values.get(f"{name}_FILE"))
        if path is not None and direct is not None and not direct.strip():
            direct = None  # `make env` leaves NAME= empty; the file wins.
        if direct is not None and path is not None:
            raise ConfigurationError(f"Set either {name} or {name}_FILE, not both.")
        if path is not None:
            values[name] = _read_secret_file(name, path)
        elif direct is not None:
            values[name] = direct
    return values


def load_settings(
    config_file: Path | None = None, *, env_file: Path | None = Path(".env")
) -> Settings:
    app = load_app_settings(config_file)

    try:
        # BaseSettings can log its raw sources in debug mode. Keep secrets out of it.
        file_values = dotenv_values(env_file, interpolate=False) if env_file is not None else {}
        secret_values = _secret_values(file_values)
        secrets = SecretSettings.model_validate(secret_values)
    except ValidationError as error:
        locations = {str(e["loc"][0]) for e in error.errors() if e["loc"]}
        invalid = ", ".join(sorted(locations.intersection(SECRET_NAMES)))
        detail = invalid or "check keys and use distinct access and signing secrets"
        raise ConfigurationError(f"Invalid or missing secrets: {detail}.") from None
    except (OSError, ValueError):
        raise ConfigurationError("Could not read the local secrets file.") from None
    return Settings(app=app, secrets=secrets)
