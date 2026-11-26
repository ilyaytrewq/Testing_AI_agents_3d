import re
import tomllib
from pathlib import Path


def test_isolated_build_dependency_is_pinned() -> None:
    manifest = Path(__file__).resolve().parents[2] / "pyproject.toml"
    requirements = tomllib.loads(manifest.read_text(encoding="utf-8"))["build-system"]["requires"]
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==\d+(?:\.\d+)+", item) for item in requirements)
