from importlib.util import find_spec
from pathlib import Path

import pytest

DOTENV = (
    "APP_ACCESS_KEY=sample_key\n"
    "APP_SESSION_SECRET=0123456789abcdef0123456789abcdef\n"
    "LLM_API_KEY=sample-provider-key\n"
    "DATABASE_URL=postgresql+asyncpg://unused.test/chat\n"
)
CONFIG = """
llm:
  base_url: https://llm.test/v1
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
    env_file.write_text(
        DOTENV + "APP_LLM__BASE_URL=https://dotenv.test/v1\nAPP_LLM__MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_LLM__MODEL", "override-model")
    monkeypatch.setenv("APP_ACCESS_KEY", "override_key")
    monkeypatch.delenv("APP_LLM__BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    configuration = load_settings(yaml_file, env_file=env_file)

    assert configuration.app.llm.model == "override-model"
    assert configuration.app.llm.base_url == "https://dotenv.test/v1"
    assert configuration.app.llm.system_prompt == "First line.\nSecond line."
    assert configuration.secrets.access_key.get_secret_value() == "override_key"
    assert configuration.secrets.llm_api_key.get_secret_value() == "sample-provider-key"


@pytest.mark.parametrize("env_file", [None, Path(".env.example")])
def test_default_config_requires_the_operator_to_set_model_and_endpoint(
    env_file: Path | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    monkeypatch.delenv("APP_LLM__BASE_URL", raising=False)
    monkeypatch.delenv("APP_LLM__MODEL", raising=False)
    with pytest.raises(ConfigurationError, match="APP_LLM__BASE_URL and APP_LLM__MODEL"):
        load_settings(Path("config/app.yaml"), env_file=env_file)


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

    model = ModelSettings(
        base_url="https://unused.test/v1", model="test", system_prompt="test prompt"
    )
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
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    env_file.write_text(
        "LLM_API_KEY=debug-fixture-provider-key\n"
        "DATABASE_URL=postgresql+asyncpg://unused.test/chat\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYDANTIC_SETTINGS_DEBUG", "1")
    with caplog.at_level("DEBUG", logger="pydantic_settings"):
        settings = load_settings(config, env_file=env_file)
    assert settings.secrets.llm_api_key.get_secret_value() == "debug-fixture-provider-key"
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


def test_generic_model_uses_the_same_secret_name_for_any_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themed_chat.settings import load_settings

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config = tmp_path / "app.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV.replace("sample-provider-key", "fixture-token"))
    settings = load_settings(config, env_file=env_file)
    assert settings.app.llm.base_url == "https://llm.test/v1"
    assert settings.secrets.llm_api_key.get_secret_value() == "fixture-token"


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///tmp/private",
        "https://test:secret@host/v1",
        "https://host/v1?key=secret",
        "https://host/v1/chat/completions",
        "http://llm.example.test/v1",
    ],
)
def test_compatible_base_url_is_required_and_is_not_a_secret_or_an_operation(
    base_url: str,
) -> None:
    from pydantic import ValidationError

    from themed_chat.settings import ModelSettings

    with pytest.raises(ValidationError) as error:
        ModelSettings(
            base_url=base_url,
            model="qwen-plus",
            system_prompt="Coffee only",
        )
    assert "key=secret" not in str(error.value)
    assert "test:secret" not in str(error.value)


def test_config_file_can_be_chosen_with_an_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themed_chat.settings import load_settings

    config = tmp_path / "elsewhere.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_CONFIG_FILE", str(config))
    for name in ("APP_ACCESS_KEY", "APP_SESSION_SECRET", "LLM_API_KEY", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert load_settings(env_file=env_file).app.llm.model == "fixture-model"
    monkeypatch.delenv("APP_CONFIG_FILE")
    from themed_chat.settings import ConfigurationError

    with pytest.raises(ConfigurationError, match="configuration file"):
        load_settings(env_file=env_file)  # The default config/app.yaml does not exist here.


def test_rate_limits_have_defaults_and_can_be_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themed_chat.settings import load_settings

    config = tmp_path / "app.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    monkeypatch.delenv("APP_AUTH__LOGIN_ATTEMPTS", raising=False)
    defaults = load_settings(config, env_file=env_file).app
    assert (defaults.auth.login_attempts, defaults.auth.login_window_seconds) == (10, 60)
    assert (defaults.chat.message_limit, defaults.chat.message_window_seconds) == (10, 60)
    monkeypatch.setenv("APP_AUTH__LOGIN_ATTEMPTS", "3")
    monkeypatch.setenv("APP_CHAT__MESSAGE_LIMIT", "5")
    configured = load_settings(config, env_file=env_file).app
    assert (configured.auth.login_attempts, configured.chat.message_limit) == (3, 5)


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:11434/v1", "http://localhost:8080/v1"])
def test_plain_http_base_url_is_allowed_only_for_loopback(base_url: str) -> None:
    from themed_chat.settings import ModelSettings

    assert ModelSettings(base_url=base_url, model="m", system_prompt="p").base_url == base_url


@pytest.mark.parametrize("variable", ["APP_LLM__BASE_URL", "APP_GUARD__CLASSIFIER_BASE_URL"])
def test_plain_http_base_url_error_names_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    from themed_chat.settings import ConfigurationError, load_app_settings

    monkeypatch.setenv(variable, "http://llm.test/v1")
    with pytest.raises(ConfigurationError, match="must use HTTPS") as error:
        load_app_settings(write_config(tmp_path))
    assert "llm.test" not in str(error.value)


def test_startup_log_names_model_hosts_but_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from themed_chat.app import log_model_targets
    from themed_chat.settings import load_settings

    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    for name in ("APP_LLM__BASE_URL", "APP_LLM__MODEL", "LLM_API_KEY", "APP_GUARD__ENABLED"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings(write_config(tmp_path), env_file=env_file)
    with caplog.at_level("INFO", logger="themed_chat.app"):
        log_model_targets(settings)
    assert "Model API: host=llm.test model=fixture-model" in caplog.text
    assert "Topic classifier API: host=llm.test" in caplog.text
    assert "sample-provider-key" not in caplog.text


@pytest.mark.parametrize(
    "extra", ["reasoning_effort: 2024-01-01", "temperature: .nan", "x: !!binary aGk="]
)
@pytest.mark.parametrize("section", ["llm", "guard"])
def test_extra_body_must_be_json_safe(tmp_path: Path, section: str, extra: str) -> None:
    from themed_chat.settings import ConfigurationError, load_app_settings

    field = "extra_body" if section == "llm" else "classifier_extra_body"
    config = tmp_path / "app.yaml"
    body = CONFIG + ("\nguard:\n" if section == "guard" else "")
    if section == "llm":
        body = body.replace("llm:\n", f"llm:\n  {field}:\n    {extra}\n", 1)
    else:
        body += f"  {field}:\n    {extra}\n"
    config.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_app_settings(config)


def test_valid_extra_body_loads(tmp_path: Path) -> None:
    from themed_chat.settings import load_app_settings

    config = tmp_path / "app.yaml"
    config.write_text(
        CONFIG + "\nguard:\n  classifier_extra_body:\n    reasoning_effort: low\n",
        encoding="utf-8",
    )
    assert load_app_settings(config).guard.classifier_extra_body == {"reasoning_effort": "low"}


SECRET_VARIABLES = (
    "APP_ACCESS_KEY",
    "APP_SESSION_SECRET",
    "LLM_API_KEY",
    "CLASSIFIER_API_KEY",
    "DATABASE_URL",
)


@pytest.fixture
def clean_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SECRET_VARIABLES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"{name}_FILE", raising=False)


def write_config(tmp_path: Path, extra: str = "") -> Path:
    config = tmp_path / "app.yaml"
    config.write_text(CONFIG + extra, encoding="utf-8")
    return config


@pytest.mark.usefixtures("clean_secrets")
def test_secrets_can_come_from_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from themed_chat.settings import load_settings

    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV.replace("LLM_API_KEY=", "UNUSED="), encoding="utf-8")
    key_file = tmp_path / "LLM_API_KEY"
    key_file.write_text("file-provider-key\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(key_file))
    settings = load_settings(write_config(tmp_path), env_file=env_file)
    # One trailing newline is removed; the rest of the value is kept as is.
    assert settings.secrets.llm_api_key.get_secret_value() == "file-provider-key"


@pytest.mark.usefixtures("clean_secrets")
def test_a_secret_and_its_file_together_are_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    key_file = tmp_path / "key"
    key_file.write_text("file-provider-key", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(key_file))
    with pytest.raises(ConfigurationError, match="LLM_API_KEY or LLM_API_KEY_FILE"):
        load_settings(write_config(tmp_path), env_file=env_file)
    monkeypatch.setenv("LLM_API_KEY_FILE", str(tmp_path / "missing"))
    env_file.write_text(DOTENV.replace("LLM_API_KEY=", "UNUSED="), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="LLM_API_KEY_FILE") as caught:
        load_settings(write_config(tmp_path), env_file=env_file)
    assert str(tmp_path) not in str(caught.value)


CLASSIFIER_ON_OTHER_HOST = """
guard:
  classifier_base_url: https://classifier.test/v1
"""


@pytest.mark.usefixtures("clean_secrets")
def test_classifier_on_another_host_needs_its_own_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    config = write_config(tmp_path, CLASSIFIER_ON_OTHER_HOST)
    with pytest.raises(ConfigurationError, match="CLASSIFIER_API_KEY"):
        load_settings(config, env_file=env_file)
    monkeypatch.setenv("CLASSIFIER_API_KEY", "classifier-key")
    settings = load_settings(config, env_file=env_file)
    assert settings.classifier_api_key.get_secret_value() == "classifier-key"
    assert settings.classifier_model_settings.base_url == "https://classifier.test/v1"
    assert settings.classifier_model_settings.model == "fixture-model"


@pytest.mark.usefixtures("clean_secrets")
def test_classifier_on_the_same_host_reuses_the_main_key(tmp_path: Path) -> None:
    from themed_chat.settings import load_settings

    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    settings = load_settings(
        write_config(tmp_path, "\nguard:\n  classifier_base_url: https://llm.test/other/v1\n"),
        env_file=env_file,
    )
    assert settings.classifier_api_key == settings.secrets.llm_api_key
    assert load_settings(write_config(tmp_path), env_file=env_file).classifier_model_settings == (
        settings.app.llm.model_copy(update={"timeout_seconds": 10.0})
    )


@pytest.mark.parametrize("url", ["http://classifier.test/v1", "https://u:p@classifier.test/v1"])
def test_classifier_base_url_follows_the_same_rules(url: str) -> None:
    from pydantic import ValidationError

    from themed_chat.settings import GuardSettings

    with pytest.raises(ValidationError):
        GuardSettings(classifier_base_url=url)
    assert GuardSettings(classifier_base_url="http://127.0.0.1:9000/v1").classifier_base_url


def test_trusted_proxies_parse_from_yaml_and_environment() -> None:
    from ipaddress import ip_network

    from pydantic import ValidationError

    from themed_chat.settings import AuthSettings

    assert AuthSettings().trusted_proxies == ()
    expected = (ip_network("10.0.0.0/8"), ip_network("fd00::/8"))
    assert AuthSettings(trusted_proxies=["10.0.0.0/8", "fd00::/8"]).trusted_proxies == expected
    assert AuthSettings(trusted_proxies='["10.0.0.0/8", "fd00::/8"]').trusted_proxies == expected
    assert AuthSettings(trusted_proxies="10.0.0.0/8, fd00::/8").trusted_proxies == expected
    for bad in ("10.0.0.1/8", "not-an-ip", "[1]"):
        with pytest.raises(ValidationError):
            AuthSettings(trusted_proxies=bad)


def test_unknown_provider_is_a_configuration_error() -> None:
    from support import make_settings

    from themed_chat.adapters.providers import PROVIDERS
    from themed_chat.app import create_app
    from themed_chat.settings import ConfigurationError, ModelSettings

    assert list(PROVIDERS) == ["openai_compatible"]
    llm = ModelSettings(
        provider="nonexistent", base_url="https://llm.test/v1", model="m", system_prompt="p"
    )
    with pytest.raises(ConfigurationError, match="llm.provider"):
        create_app(make_settings(llm=llm))


@pytest.mark.usefixtures("clean_secrets")
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_secret_next_to_its_file_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    from themed_chat.settings import load_settings

    env_file = tmp_path / ".env"
    # As written by `make env`: LLM_API_KEY= stays empty.
    env_file.write_text(
        DOTENV.replace("LLM_API_KEY=sample-provider-key", f"LLM_API_KEY={blank}"),
        encoding="utf-8",
    )
    key_file = tmp_path / "key"
    key_file.write_text("file-provider-key\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(key_file))
    settings = load_settings(write_config(tmp_path), env_file=env_file)
    assert settings.secrets.llm_api_key.get_secret_value() == "file-provider-key"


@pytest.mark.usefixtures("clean_secrets")
@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9000/v1", "https://llm.test:8443/v1", "https://LLM.test/other"]
)
def test_main_key_goes_only_to_the_same_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    from themed_chat.settings import ConfigurationError, load_settings

    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV, encoding="utf-8")
    config = write_config(tmp_path, f"\nguard:\n  classifier_base_url: {url}\n")
    if url == "https://LLM.test/other":
        # Same scheme, host (case-insensitive) and default port: the main key is reused.
        settings = load_settings(config, env_file=env_file)
        assert settings.classifier_api_key == settings.secrets.llm_api_key
        return
    with pytest.raises(ConfigurationError, match="CLASSIFIER_API_KEY"):
        load_settings(config, env_file=env_file)
    monkeypatch.setenv("CLASSIFIER_API_KEY", "classifier-key")
    assert load_settings(config, env_file=env_file).classifier_api_key.get_secret_value() == (
        "classifier-key"
    )
