from dataclasses import dataclass
from os import environ
from pathlib import Path
from re import compile as compile_pattern
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import (
    AnyHttpUrl,
    BaseModel,
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
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ConfigurationError(RuntimeError):
    """Operator-facing error that never contains a raw settings value."""


class ConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class ChatSettings(ConfigSection):
    title: NonBlank = "Кофейный бариста"


class ModelSettings(ConfigSection):
    provider: Literal["gemini"] = "gemini"
    model: NonBlank
    system_prompt: NonBlank
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 25.0
    max_output_tokens: Annotated[int, Field(gt=0, le=8192)] = 1024


class DatabaseSettings(ConfigSection):
    backend: Literal["sqlite", "postgresql"] = "sqlite"
    sqlite_path: Path = Path("data/chat.sqlite3")

    @field_validator("sqlite_path", mode="before")
    @classmethod
    def validate_sqlite_path(cls, value: object) -> object:
        if isinstance(value, str) and (not value.strip() or value.strip() == ":memory:"):
            raise ValueError("use a persistent SQLite file")
        return value


class AuthSettings(ConfigSection):
    public_origin: str = "http://127.0.0.1:8000"
    session_ttl_seconds: Annotated[int, Field(ge=1, le=604800)] = 28800

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
        if canonical.scheme == "http" and canonical.host not in {"127.0.0.1", "localhost", "[::1]"}:
            raise ValueError("HTTPS is required outside loopback hosts")
        return str(canonical).removesuffix("/")


class AppSettings(ConfigSection):
    chat: ChatSettings = ChatSettings()
    llm: ModelSettings
    db: DatabaseSettings = DatabaseSettings()
    auth: AuthSettings = AuthSettings()


APP_SECTIONS: dict[str, type[ConfigSection]] = {
    "chat": ChatSettings,
    "llm": ModelSettings,
    "db": DatabaseSettings,
    "auth": AuthSettings,
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


SECRET_NAMES = ("APP_ACCESS_KEY", "APP_SESSION_SECRET", "GEMINI_API_KEY", "DATABASE_URL")


class SecretSettings(ConfigSection):
    access_key: SecretStr = Field(validation_alias="APP_ACCESS_KEY")
    session_secret: SecretStr = Field(validation_alias="APP_SESSION_SECRET")
    gemini_api_key: SecretStr = Field(validation_alias="GEMINI_API_KEY")
    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")

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

    @field_validator("gemini_api_key", "database_url")
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


def load_settings(
    config_file: Path = DEFAULT_CONFIG_FILE, *, env_file: Path | None = Path(".env")
) -> Settings:
    try:
        if not config_file.is_file():
            raise ConfigurationError("Application YAML configuration file was not found.")
        yaml_values: object = safe_load(config_file.read_text(encoding="utf-8"))
        app = AppSettings.model_validate(_apply_environment_overrides(yaml_values))
    except (OSError, ValueError, YAMLError):
        raise ConfigurationError(
            "Invalid application configuration. Check the YAML file and APP_ overrides."
        ) from None

    try:
        # BaseSettings can log its raw sources in debug mode. Keep secrets out of it.
        file_values = dotenv_values(env_file, interpolate=False) if env_file is not None else {}
        secret_values = {
            name: value
            for name in SECRET_NAMES
            if (value := environ.get(name, file_values.get(name))) is not None
        }
        secrets = SecretSettings.model_validate(secret_values)
    except ValidationError as error:
        locations = {str(e["loc"][0]) for e in error.errors() if e["loc"]}
        invalid = ", ".join(sorted(locations.intersection(SECRET_NAMES)))
        detail = invalid or "check keys and use distinct access and signing secrets"
        raise ConfigurationError(f"Invalid or missing secrets: {detail}.") from None
    except (OSError, ValueError):
        raise ConfigurationError("Could not read the local secrets file.") from None
    if app.db.backend == "postgresql" and secrets.database_url is None:
        raise ConfigurationError("DATABASE_URL is required with the postgresql backend.")
    return Settings(app=app, secrets=secrets)
