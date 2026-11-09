"""Shared fixtures for the practicum test suite."""

import json
import shutil
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

from practicum.sim import load_simulator

REPO_ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = REPO_ROOT / "docs" / "assets" / "py" / "minibazel.py"

MODULE_BAZEL = 'module(name = "demo")\n\nbazel_dep(name = "rules_python", version = "2.4.6")\n'
BUILD_START = 'load("@rules_python//python:defs.bzl", "py_binary")\n\npy_binary(name = "hello", srcs = ["hello.py"])\n'


def write_manifest(
    site: Path, parts: list[dict[str, object]], reference: list[dict[str, object]] | None = None
) -> None:
    js = site / "assets" / "js"
    js.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"title": "T", "parts": parts, "reference": reference or []})
    (js / "curriculum.js").write_text(f"window.CURRICULUM = {payload};\n", encoding="utf-8")


def page(body: str, *, title: str = "Page") -> str:
    return f"<!doctype html><html><head><title>{title}</title></head><body>{textwrap.dedent(body)}</body></html>"


def write_files(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def mb() -> ModuleType:
    """The real simulator module (docs/assets/py/minibazel.py)."""
    return load_simulator(REPO_ROOT / "docs")


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A minimal practicum repository: one lab (starter, solution, grading overlay, checks) and a tiny site."""
    (tmp_path / "pixi.toml").write_text("[workspace]\nname = 'x'\n", encoding="utf-8")
    lab = tmp_path / "labs" / "m01-lab1"
    write_files(
        lab,
        {
            "lab.toml": 'id = "m01-lab1"\ntitle = "Demo lab"\nmodule = "m01"\ntimeout = 60\n',
            "starter/.bazelversion": "9.3.2\n",
            "starter/MODULE.bazel": MODULE_BAZEL,
            "starter/app/BUILD.bazel": "# TODO\n",
            "starter/app/hello.py": "print('Hello')\n",
            "starter/bazel-out/junk.txt": "ignored",
            "solution/.bazelversion": "9.3.2\n",
            "solution/MODULE.bazel": MODULE_BAZEL,
            "solution/app/BUILD.bazel": BUILD_START,
            "solution/app/hello.py": "print('Hello')\n",
            "grading/grade/BUILD.bazel": "# grading overlay\n",
            "checks.toml": textwrap.dedent(
                """
                [[check]]
                name = "the app runs"
                command = ["run", "//app:hello"]
                stdout_contains = ["Hello"]
                message = "Add a py_binary."

                [[check]]
                name = "the overlay is present"
                file_exists = ["grade/BUILD.bazel"]
                """
            ),
        },
    )
    site = tmp_path / "docs"
    write_manifest(site, [{"id": "part1", "modules": [{"id": "m01", "href": "modules/m01.html"}], "projects": []}])
    (site / "modules").mkdir()
    (site / "modules" / "m01.html").write_text(
        page('<main><h1>M01</h1><div class="lab" data-id="m01-lab1"></div></main>'), encoding="utf-8"
    )
    (site / "assets" / "py").mkdir(parents=True)
    shutil.copy(SIMULATOR, site / "assets" / "py" / "minibazel.py")
    return tmp_path
