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
