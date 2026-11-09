"""Differential test: the simulator against real Bazel 9.3.2 on a few small workspaces.

Each case is written to a temporary directory. For every command the simulator's `query` labels (main repository
only, since real Bazel also reports implicit and toolchain dependencies) and the pass/fail of `bazel build --nobuild`
must match real Bazel. The first run downloads Bazel and the rule sets (a few minutes); later runs reuse the caches.
"""

import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

from practicum.sim import load_simulator
from tests.conftest import REPO_ROOT, write_files

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("bazelisk") is None, reason="bazelisk is not on PATH (run through pixi)"),
]

mb: Any = load_simulator(REPO_ROOT / "docs")

MODULE = textwrap.dedent(
    """
    module(name = "diff")

    bazel_dep(name = "rules_python", version = "2.4.6")
    bazel_dep(name = "bazel_skylib", version = "1.9.2")
    bazel_dep(name = "platforms", version = "1.1.0")

    python = use_extension("@rules_python//python/extensions:python.bzl", "python")
    python.toolchain(python_version = "3.13", is_default = True)
    """
)
PY = 'load("@rules_python//python:defs.bzl", "py_binary", "py_library", "py_test")\n'

CASES: dict[str, tuple[dict[str, str], list[str]]] = {
    "graph-and-query": (
        {
            "a/BUILD.bazel": PY
            + 'py_library(name = "l1", srcs = ["l1.py"], deps = [":l2"])\n'
            + 'py_library(name = "l2", srcs = ["l2.py"], deps = ["//b:l3"])\n'
            + 'py_binary(name = "app", srcs = ["app.py"], deps = [":l1"], tags = ["x"])\n',
            "b/BUILD.bazel": PY
            + 'py_library(name = "l3", srcs = ["l3.py"], visibility = ["//visibility:public"])\n'
            + 'py_test(name = "t", srcs = ["t.py"], deps = [":l3"], size = "small")\n'
            + 'py_test(name = "m", srcs = ["m.py"], tags = ["manual"])\n',
            **{f"{p}.py": "" for p in ("a/l1", "a/l2", "a/app", "b/l3", "b/t", "b/m")},
        },
        [
            "query //...",
            "query deps(//a:app)",
            "query rdeps(//...,//b:l3,1)",
            "query somepath(//a:app,//b:l3)",
            "query kind(py_library,//...)",
            "query attr(tags,x,//...)",
            "query tests(//...)",
            "query //b:*",
            "query //...-//a/...",
            "build //...",
        ],
    ),
    "visibility-and-labels": (
        {
            "lib/BUILD.bazel": 'filegroup(name = "p", srcs = ["f.txt"], visibility = ["//ok:__subpackages__"])\n',
            "lib/f.txt": "",
            "ok/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
            "ok/sub/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
            "bad/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
            "file/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:f.txt"])\n',
            "py/BUILD.bazel": PY + 'py_library(name = "l", deps = [":nope"])\npy_binary(name = "b", srcs = ["x.py"])\n',
        },
        ["build //ok:u //ok/sub:u", "build //bad:u", "build //file:u", "build //py:l", "build //py:b"],
    ),
    "select": (
        {
            "c/BUILD.bazel": textwrap.dedent(
                """
                config_setting(name = "opt", values = {"compilation_mode": "opt"})
                config_setting(name = "fast", define_values = {"mode": "fast"})
                filegroup(name = "d1")
                filegroup(name = "d2")
                filegroup(name = "a", srcs = select({":opt": [":d1"], "//conditions:default": [":d2"]}))
                filegroup(name = "b", srcs = select({":fast": [":d1"]}))
                """
            ),
        },
        ["query deps(//c:a)", "build //c:a", "build //c:b", "build //c:b --define=mode=fast"],
    ),
}


def _real(workspace: Path, words: list[str]) -> tuple[bool, list[str]]:
    command, rest = words[0], words[1:]
    args = [command, "--nobuild", *rest] if command == "build" else [command, *rest]
    done = subprocess.run(
        ["bazelisk", "--max_idle_secs=60", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    labels = sorted(line for line in done.stdout.splitlines() if line.startswith("//"))
    return done.returncode == 0, labels


def _simulated(files: dict[str, str], words: list[str]) -> tuple[bool, list[str]]:
    bazel = mb.Bazel(files)
    if words[0] == "query":
        try:
            return True, sorted(x for x in bazel.query(words[1]) if x.startswith("//"))
        except mb.BazelError:
            return False, []
    result = bazel.build(*words[1:])
    return bool(result.ok), []


@pytest.mark.parametrize("case", sorted(CASES))
def test_simulator_matches_real_bazel(case: str, tmp_path: Path) -> None:
    files, commands = CASES[case]
    workspace_files = {"MODULE.bazel": MODULE, ".bazelversion": "9.3.2\n", **files}
    write_files(tmp_path, workspace_files)
    mismatches: list[str] = []
    try:
        for command in commands:
            words = command.split()
            real = _real(tmp_path, words)
            sim = _simulated(workspace_files, words)
            if real != sim:
                mismatches.append(f"{command}: real={real} simulated={sim}")
    finally:
        # Each workspace starts its own Bazel server; stop it so none stays behind holding memory.
        subprocess.run(["bazelisk", "shutdown"], cwd=tmp_path, capture_output=True, timeout=120, check=False)
    assert not mismatches, "\n".join(mismatches)
