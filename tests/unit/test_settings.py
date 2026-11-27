from importlib.util import find_spec
from pathlib import Path

import pytest

DOTENV = (
    "APP_ACCESS_KEY=sample_key\n"
    "APP_SESSION_SECRET=0123456789abcdef0123456789abcdef\n"
    "GEMINI_API_KEY=sample-provider-key\n"
    "DATABASE_URL=postgresql+asyncpg://unused.test/chat\n"
)
CONFIG = """
llm:
  model: fixture-model
  system_prompt: |-
    First line.
    Second line.
"""


def test_process_environment_overrides_yaml_and_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert find_spec("themed_chat.settings") is not None, "settings loader is not installed"
    from themed_chat.settings import load_settings

    yaml_file = tmp_path / "app.yaml"
    yaml_file.write_text(CONFIG, encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    monkeypatch.setenv("APP_LLM__MODEL", "override-model")
    monkeypatch.setenv("APP_ACCESS_KEY", "override_key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    configuration = load_settings(yaml_file, env_file=env_file)

    assert configuration.app.llm.model == "override-model"
    assert configuration.app.llm.system_prompt == "First line.\nSecond line."
    assert configuration.secrets.access_key.get_secret_value() == "override_key"
    assert configuration.secrets.gemini_api_key.get_secret_value() == "sample-provider-key"


def test_invalid_secret_is_not_in_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    config_file = tmp_path / "config.yaml"
    config_file.write_text(CONFIG, encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    secret = "not!a!valid!key"
    monkeypatch.setenv("APP_ACCESS_KEY", secret)
    with pytest.raises(ConfigurationError, match="APP_ACCESS_KEY") as caught:
        load_settings(config_file, env_file=env_file)
    assert secret not in str(caught.value)


def test_postgresql_requires_a_secret_dsn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    config_file = tmp_path / "app.yaml"
    config_file.write_text(CONFIG, encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV.split("DATABASE_URL=")[0], encoding="utf-8")
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        load_settings(config_file, env_file=env_file)


def test_non_loopback_origin_requires_https(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    config_file = tmp_path / "app.yaml"
    config_file.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("APP_AUTH__PUBLIC_ORIGIN", "http://chat.example.test")
    with pytest.raises(ConfigurationError, match="Invalid application configuration"):
        load_settings(config_file, env_file=None)


@pytest.mark.parametrize(
    "yaml_text",
    [CONFIG + "\n_env_prefix: CUSTOM_\n", CONFIG + "\n123: unexpected\n", "- not a mapping\n"],
)
def test_yaml_rejects_invalid_top_level(yaml_text: str, tmp_path: Path) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    yaml_file = tmp_path / "app.yaml"
    yaml_file.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Invalid application configuration"):
        load_settings(yaml_file, env_file=None)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://пример.рф", "https://xn--e1afmkfd.xn--p1ai"),
        ("http://[0:0:0:0:0:0:0:1]:80", "http://[::1]"),
    ],
)
def test_origin_is_serialized_like_a_browser(value: str, expected: str) -> None:
    from themed_chat.settings import AuthSettings

    assert AuthSettings(public_origin=value).public_origin == expected


def test_default_timeout_has_the_declared_float_type() -> None:
    from themed_chat.settings import ModelSettings

    model = ModelSettings(model="test", system_prompt="test prompt")
    assert type(model.timeout_seconds) is float


def test_debug_logging_does_not_emit_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from themed_chat.settings import load_settings

    config = tmp_path / "app.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    env_file = tmp_path / ".env"
    monkeypatch.setenv("APP_ACCESS_KEY", "debug_fixture_key")
    monkeypatch.setenv("APP_SESSION_SECRET", "separate-synthetic-debug-signing-key-1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env_file.write_text(
        "GEMINI_API_KEY=debug-fixture-provider-key\n"
        "DATABASE_URL=postgresql+asyncpg://unused.test/chat\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYDANTIC_SETTINGS_DEBUG", "1")
    with caplog.at_level("DEBUG", logger="pydantic_settings"):
        settings = load_settings(config, env_file=env_file)
    assert settings.secrets.gemini_api_key.get_secret_value() == "debug-fixture-provider-key"
    for value in (
        "debug_fixture_key",
        "separate-synthetic-debug-signing-key-1",
        "debug-fixture-provider-key",
    ):
        assert value not in caplog.text


def test_rejected_yaml_values_are_not_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    config = tmp_path / "app.yaml"
    marker = "test-value-in-invalid-settings-field"
    config.write_text(CONFIG + f"  gemini_api_key: {marker}\n", encoding="utf-8")
    monkeypatch.setenv("PYDANTIC_SETTINGS_DEBUG", "1")
    with caplog.at_level("DEBUG", logger="pydantic_settings"), pytest.raises(ConfigurationError):
        load_settings(config, env_file=None)
    assert marker not in caplog.text
