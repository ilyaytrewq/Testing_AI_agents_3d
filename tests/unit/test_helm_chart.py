import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[2] / "deploy/helm/themed-chat"


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
            "--set",
            "image.repository=example.test/chat,existingSecret=chat-runtime",
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
    expected_secrets = {"DATABASE_URL", "APP_ACCESS_KEY", "APP_SESSION_SECRET", "GEMINI_API_KEY"}
    assert {
        value["name"]: value["valueFrom"]["secretKeyRef"]
        for value in container["env"]
        if "valueFrom" in value
    } == {key: {"name": "chat-runtime", "key": key} for key in expected_secrets}
    assert container["startupProbe"]["httpGet"]["path"] == "/healthz"
    assert container["readinessProbe"]["httpGet"]["path"] == "/healthz"
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
            "--set",
            "image.repository=example.test/chat,existingSecret=chat-runtime",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "release name must start with a letter" in result.stderr


def test_helm_selects_compatible_model_and_only_its_key(helm: str) -> None:
    arguments = (
        "image.repository=example.test/chat,existingSecret=chat-runtime,"
        "llm.provider=openai_compatible,llm.baseUrl=https://qwen.test/compatible-mode/v1,"
        "llm.model=qwen-plus"
    )
    result = subprocess.run(
        [helm, "template", "coffee", str(CHART), "--set-string", arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    documents = {item["kind"]: item for item in yaml.safe_load_all(result.stdout)}
    env = {
        item["name"]: item
        for item in documents["Deployment"]["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert "GEMINI_API_KEY" not in env
    assert env["OPENAI_COMPATIBLE_API_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "chat-runtime",
        "key": "OPENAI_COMPATIBLE_API_KEY",
    }
    assert env["APP_LLM__PROVIDER"]["value"] == "openai_compatible"
    assert env["APP_LLM__BASE_URL"]["value"] == "https://qwen.test/compatible-mode/v1"
    assert env["APP_LLM__MODEL"]["value"] == "qwen-plus"


def test_helm_requires_compatible_base_url(helm: str) -> None:
    result = subprocess.run(
        [
            helm,
            "template",
            "coffee",
            str(CHART),
            "--set-string",
            "image.repository=example.test/chat,existingSecret=chat-runtime,"
            "llm.provider=openai_compatible,llm.model=qwen-plus",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "llm.baseUrl is required" in result.stderr
