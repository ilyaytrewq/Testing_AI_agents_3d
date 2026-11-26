from importlib.util import find_spec
from pathlib import Path

import pytest

DOTENV = (
    "APP_ACCESS_KEY=sample_key\n"
    "APP_SESSION_SECRET=0123456789abcdef0123456789abcdef\n"
    "GEMINI_API_KEY=sample-provider-key\n"
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
    config_file.write_text(CONFIG + "\ndb: {backend: postgresql}\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
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
