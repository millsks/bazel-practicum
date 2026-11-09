from pathlib import Path

import pytest

from practicum.sim import load_simulator, simulator_path
from tests.conftest import REPO_ROOT


def test_simulator_path_points_into_assets(tmp_path: Path) -> None:
    assert simulator_path(tmp_path) == tmp_path / "assets" / "py" / "minibazel.py"


def test_load_simulator_is_cached() -> None:
    first = load_simulator(REPO_ROOT / "docs")
    assert load_simulator(REPO_ROOT / "docs") is first
    assert first.BAZEL_VERSION == "9.3.2"


def test_load_simulator_from_another_site(fake_repo: Path) -> None:
    module = load_simulator(fake_repo / "docs")
    assert module is not load_simulator(REPO_ROOT / "docs")
    assert hasattr(module, "Bazel")


def test_missing_simulator_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="simulator not found"):
        load_simulator(tmp_path)
