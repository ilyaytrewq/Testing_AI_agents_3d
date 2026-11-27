import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[2] / "deploy/helm/themed-chat"
RUNTIME_VALUES = "image.repository=example.test/chat,existingSecret=chat-runtime"
MODEL_VALUES = "llm.baseUrl=https://llm.example.test/v1,llm.model=any-model"


@pytest.fixture
def helm() -> str:
    executable = shutil.which("helm")
    if executable is None:
        pytest.skip("Install Helm to check the chart.")
    return executable


def test_helm_runs_one_non_root_replica_with_external_secrets(helm: str) -> None:
    result = subprocess.run(
        [
            helm,
            "template",
            "coffee",
            str(CHART),
            "--set-string",
            f"{RUNTIME_VALUES},{MODEL_VALUES}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    documents = {item["kind"]: item for item in yaml.safe_load_all(result.stdout)}
    assert set(documents) == {"Deployment", "Service"}
    deployment = documents["Deployment"]["spec"]
    assert deployment["replicas"] == 1
    assert deployment["strategy"]["type"] == "Recreate"
    pod = deployment["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    container = pod["containers"][0]
    expected_secrets = {"DATABASE_URL", "APP_ACCESS_KEY", "APP_SESSION_SECRET", "LLM_API_KEY"}
    # Secrets are mounted as files; no secret value is in the environment.
    assert not [value for value in container["env"] if "valueFrom" in value]
    env = {item["name"]: item.get("value") for item in container["env"]}
    assert {name: value for name, value in env.items() if name.endswith("_FILE")} == {
        f"{key}_FILE": f"/run/secrets/themed-chat/{key}" for key in expected_secrets
    }
    assert expected_secrets.isdisjoint(env)
    [mount] = container["volumeMounts"]
    assert mount == {
        "name": "runtime-secrets",
        "mountPath": "/run/secrets/themed-chat",
        "readOnly": True,
    }
    [volume] = pod["volumes"]
    assert volume["secret"]["secretName"] == "chat-runtime"
    assert {item["key"] for item in volume["secret"]["items"]} == expected_secrets
    assert pod["securityContext"]["fsGroup"] == 10001
    assert "APP_AUTH__TRUSTED_PROXIES" not in env and "APP_GUARD__CLASSIFIER_BASE_URL" not in env
    assert "APP_LLM__PROVIDER" not in env
    assert container["startupProbe"]["httpGet"]["path"] == "/readyz"
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    service = documents["Service"]["spec"]
    assert service["type"] == "ClusterIP"
    assert service["selector"] == deployment["selector"]["matchLabels"]


def test_helm_requires_existing_secret(helm: str) -> None:
    result = subprocess.run(
        [helm, "template", "coffee", str(CHART), "--set", "image.repository=example.test/chat"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "existingSecret is required" in result.stderr


@pytest.mark.parametrize("release", ["coffee.prod", "2coffee"])
def test_helm_rejects_release_names_unsupported_by_the_service(release: str, helm: str) -> None:
    result = subprocess.run(
        [
            helm,
            "template",
            release,
            str(CHART),
            "--set-string",
            f"{RUNTIME_VALUES},{MODEL_VALUES}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "release name must start with a letter" in result.stderr


def test_helm_llm_overrides_set_model_and_endpoint(helm: str) -> None:
    result = subprocess.run(
        [
            helm,
            "template",
            "coffee",
            str(CHART),
            "--set-string",
            RUNTIME_VALUES,
            "--set-string",
            "llm.baseUrl=https://llm.example.test/v1",
            "--set-string",
            "llm.model=any-model",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    documents = {item["kind"]: item for item in yaml.safe_load_all(result.stdout)}
    env = {
        item["name"]: item
        for item in documents["Deployment"]["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert {name: item["value"] for name, item in env.items() if name.startswith("APP_LLM__")} == {
        "APP_LLM__BASE_URL": "https://llm.example.test/v1",
        "APP_LLM__MODEL": "any-model",
    }
    assert env["LLM_API_KEY_FILE"]["value"] == "/run/secrets/themed-chat/LLM_API_KEY"


@pytest.mark.parametrize(
    "override", ["", ",llm.model=any-model", ",llm.baseUrl=https://llm.test/v1"]
)
def test_helm_requires_both_model_and_endpoint(helm: str, override: str) -> None:
    result = subprocess.run(
        [
            helm,
            "template",
            "coffee",
            str(CHART),
            "--set-string",
            f"{RUNTIME_VALUES}{override}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "llm.model and llm.baseUrl are required" in result.stderr


def test_helm_trusted_proxies_and_classifier_options(helm: str) -> None:
    result = subprocess.run(
        [
            helm,
            "template",
            "coffee",
            str(CHART),
            "--set-string",
            f"{RUNTIME_VALUES},{MODEL_VALUES}",
            "--set",
            "trustedProxies={10.0.0.0/8,fd00::/8}",
            "--set-string",
            "classifier.baseUrl=https://classifier.example.test/v1",
            "--set",
            "classifier.apiKeyInSecret=true",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    documents = {item["kind"]: item for item in yaml.safe_load_all(result.stdout)}
    pod = documents["Deployment"]["spec"]["template"]["spec"]
    env = {item["name"]: item.get("value") for item in pod["containers"][0]["env"]}
    assert env["APP_AUTH__TRUSTED_PROXIES"] == '["10.0.0.0/8","fd00::/8"]'
    assert env["APP_GUARD__CLASSIFIER_BASE_URL"] == "https://classifier.example.test/v1"
    assert env["CLASSIFIER_API_KEY_FILE"] == "/run/secrets/themed-chat/CLASSIFIER_API_KEY"
    [volume] = pod["volumes"]
    assert "CLASSIFIER_API_KEY" in {item["key"] for item in volume["secret"]["items"]}

    from themed_chat.settings import AuthSettings

    assert len(AuthSettings(trusted_proxies=env["APP_AUTH__TRUSTED_PROXIES"]).trusted_proxies) == 2
