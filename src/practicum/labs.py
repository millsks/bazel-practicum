"""Discover, start, and grade the local labs, which run real Bazel.

A lab directory ``labs/<id>/`` holds:

- ``lab.toml``: ``id``, ``title``, ``module`` (the page that introduces it), optional ``timeout`` in seconds.
- ``starter/``: the workspace the learner starts from (``MODULE.bazel``, ``.bazelversion``, BUILD files, sources).
- ``solution/``: a reference workspace that passes every check.
- ``grading/`` (optional): files laid over the learner's copy before grading, such as extra tests.
- ``checks.toml``: an ordered list of ``[[check]]`` tables, each running one Bazel command and asserting on it.

Grading copies the chosen workspace and the grading overlay into ``build/labs/<id>-<source>/``, so the learner's
copy in ``work/<id>/`` never contains grading files and cannot edit them.
"""

import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

_IGNORED = shutil.ignore_patterns("bazel-*", ".git", "MODULE.bazel.lock", "__pycache__", "*.pyc")
_CHECK_KEYS = frozenset(
    {
        "name",
        "command",
        "expect",
        "stdout_contains",
        "stdout_lacks",
        "stdout_equals",
        "stdout_lines",
        "output_contains",
        "output_lacks",
        "output_matches",
        "message",
        "file_exists",
        "file_contains",
    }
)


class LabError(RuntimeError):
    """Raised for an unknown lab, an invalid lab definition, or a missing Bazel."""


class Source(StrEnum):
    """Which copy of a lab's workspace a grading run uses."""

    WORK = "work"
    STARTER = "starter"
    SOLUTION = "solution"


@dataclass(frozen=True, slots=True)
class Check:
    """One assertion: run ``bazel <command>`` in the staged workspace and inspect the result.

    Attributes:
        name: What the check verifies, shown to the learner.
        command: Bazel arguments, such as ``["test", "//..."]``; empty for file-only checks.
        expect: ``success`` (exit code 0), ``failure`` (non-zero), or ``any``.
        stdout_contains: Substrings stdout must contain.
        stdout_lacks: Substrings stdout must not contain.
        stdout_equals: Exact stdout after stripping surrounding whitespace, or ``None``.
        stdout_lines: Exact set of non-empty stdout lines (order-insensitive), or ``None``.
        output_contains: Substrings stdout or stderr must contain.
        output_lacks: Substrings neither stdout nor stderr may contain.
        output_matches: Regular expressions searched in stdout + stderr.
        message: A hint shown when the check fails.
        file_exists: Workspace-relative paths that must exist (after the command, if any).
        file_contains: Mapping of workspace-relative path to a substring it must contain.
    """

    name: str
    command: tuple[str, ...] = ()
    expect: str = "success"
    stdout_contains: tuple[str, ...] = ()
    stdout_lacks: tuple[str, ...] = ()
    stdout_equals: str | None = None
    stdout_lines: tuple[str, ...] | None = None
    output_contains: tuple[str, ...] = ()
    output_lacks: tuple[str, ...] = ()
    output_matches: tuple[str, ...] = ()
    message: str = ""
    file_exists: tuple[str, ...] = ()
    file_contains: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of one check.

    Attributes:
        name: The check's name.
        ok: Whether it passed.
        detail: Why it failed (empty when it passed).
    """

    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Lab:
    """A lab defined by ``labs/<id>/lab.toml``.

    Attributes:
        id: Identifier such as ``m01-lab1`` or ``c1``.
        title: Human-readable title.
        module: Id of the page that introduces the lab, such as ``m01``.
        path: The lab directory.
        timeout: Seconds allowed per Bazel command.
    """

    id: str
    title: str
    module: str
    path: Path
    timeout: int = 900

    @property
    def starter_dir(self) -> Path:
        """The starter workspace."""
        return self.path / "starter"

    @property
    def solution_dir(self) -> Path:
        """The reference solution workspace."""
        return self.path / "solution"

    @property
    def grading_dir(self) -> Path:
        """Files laid over the workspace before grading."""
        return self.path / "grading"

    def work_dir(self, root: Path) -> Path:
        """Return the learner's copy: ``work/<id>`` under ``root``.

        Args:
            root: Repository root.

        Returns:
            The working copy path.
        """
        return root / "work" / self.id


def load_lab(lab_dir: Path) -> Lab:
    """Load a lab definition from ``lab_dir/lab.toml``.

    Args:
        lab_dir: The lab directory.

    Returns:
        The parsed lab.

    Raises:
        LabError: If the file is missing, invalid, or lacks required keys.
    """
    path = lab_dir / "lab.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LabError(f"missing {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise LabError(f"invalid TOML in {path}: {exc}") from exc
    try:
        return Lab(
            id=str(data["id"]),
            title=str(data["title"]),
            module=str(data["module"]),
            path=lab_dir,
            timeout=int(data.get("timeout", 900)),
        )
    except KeyError as exc:
        raise LabError(f"{path} is missing key {exc.args[0]!r}") from exc


def load_checks(lab: Lab) -> list[Check]:
    """Load a lab's ``checks.toml``.

    Args:
        lab: The lab.

    Returns:
        Checks in file order.

    Raises:
        LabError: If the file is missing or a check is malformed.
    """
    path = lab.path / "checks.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LabError(f"missing {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise LabError(f"invalid TOML in {path}: {exc}") from exc
    raw = data.get("check")
    if not isinstance(raw, list) or not raw:
        raise LabError(f"{path} needs at least one [[check]] table")
    checks: list[Check] = []
    for number, entry in enumerate(raw, start=1):
        unknown = set(entry) - _CHECK_KEYS
        if unknown:
            raise LabError(f"{path}: check {number} has unknown keys: {', '.join(sorted(unknown))}")
        if "name" not in entry:
            raise LabError(f"{path}: check {number} has no name")
        expect = str(entry.get("expect", "success"))
        if expect not in ("success", "failure", "any"):
            raise LabError(f"{path}: check {number}: expect must be success, failure, or any")
        command = tuple(str(c) for c in entry.get("command", ()))
        if not command and not entry.get("file_exists") and not entry.get("file_contains"):
            raise LabError(f"{path}: check {number} has no command and no file assertions")
        lines = entry.get("stdout_lines")
        checks.append(
            Check(
                name=str(entry["name"]),
                command=command,
                expect=expect,
                stdout_contains=tuple(entry.get("stdout_contains", ())),
                stdout_lacks=tuple(entry.get("stdout_lacks", ())),
                stdout_equals=entry.get("stdout_equals"),
                stdout_lines=tuple(lines) if lines is not None else None,
                output_contains=tuple(entry.get("output_contains", ())),
                output_lacks=tuple(entry.get("output_lacks", ())),
                output_matches=tuple(entry.get("output_matches", ())),
                message=str(entry.get("message", "")),
                file_exists=tuple(entry.get("file_exists", ())),
                file_contains=dict(entry.get("file_contains", {})),
            )
        )
    return checks


def discover_labs(root: Path) -> list[Lab]:
    """Return every lab under ``root/labs``, sorted by id.

    Args:
        root: Repository root.

    Returns:
        Labs ordered by identifier.
    """
    found = [load_lab(p.parent) for p in (root / "labs").glob("*/lab.toml")]
    return sorted(found, key=lambda lab: lab.id)


def get_lab(root: Path, lab_id: str) -> Lab:
    """Look up a lab by id.

    Args:
        root: Repository root.
        lab_id: Identifier such as ``m01-lab1``.

    Returns:
        The lab.

    Raises:
        LabError: If no lab has that id.
    """
    for lab in discover_labs(root):
        if lab.id == lab_id or lab.path.name == lab_id:
            return lab
    raise LabError(f"unknown lab {lab_id!r}; run `pixi run labs` to list them")


def start_lab(root: Path, lab: Lab, *, force: bool = False) -> Path:
    """Copy a lab's starter workspace to ``work/<id>``.

    Args:
        root: Repository root.
        lab: The lab.
        force: Replace an existing working copy.

    Returns:
        The working copy.

    Raises:
        LabError: If a working copy exists and ``force`` is false.
    """
    destination = lab.work_dir(root)
    if destination.exists():
        if not force:
            raise LabError(f"{destination} already exists; pass --force to start over (your changes will be lost)")
        shutil.rmtree(destination)
    shutil.copytree(lab.starter_dir, destination, ignore=_IGNORED)
    return destination


def resolve_source(root: Path, lab: Lab, source: Source | None) -> tuple[Source, Path]:
    """Pick which workspace to grade: the learner's copy when it exists, else the starter.

    Args:
        root: Repository root.
        lab: The lab.
        source: An explicit choice, or ``None``.

    Returns:
        The chosen source and its directory.
    """
    if source is None:
        source = Source.WORK if lab.work_dir(root).is_dir() else Source.STARTER
    return source, {Source.WORK: lab.work_dir(root), Source.STARTER: lab.starter_dir, Source.SOLUTION: lab.solution_dir}[
        source
    ]


def stage_lab(root: Path, lab: Lab, source: Source) -> Path:
    """Copy a workspace plus the grading overlay into ``build/labs/<id>-<source>/``.

    Args:
        root: Repository root.
        lab: The lab.
        source: Which workspace to copy.

    Returns:
        The staged workspace.

    Raises:
        LabError: If the chosen workspace has no ``MODULE.bazel``.
    """
    _, code_dir = resolve_source(root, lab, source)
    if not (code_dir / "MODULE.bazel").is_file():
        raise LabError(f"{code_dir} has no MODULE.bazel")
    staged = root / "build" / "labs" / f"{lab.id}-{source.value}"
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(code_dir, staged, ignore=_IGNORED)
    if lab.grading_dir.is_dir():
        shutil.copytree(lab.grading_dir, staged, dirs_exist_ok=True)
    return staged


def find_bazel() -> str:
    """Locate Bazelisk (preferred) or Bazel.

    Returns:
        The executable path.

    Raises:
        LabError: If neither is on ``PATH``; run through ``pixi run`` so the course's Bazelisk is active.
    """
    for name in ("bazelisk", "bazel"):
        found = shutil.which(name)
        if found:
            return found
    raise LabError("bazelisk not found; run this through `pixi run` so the course's Bazelisk is on PATH")


Runner = Callable[[list[str], Path, int], tuple[int, str, str]]


def _run(command: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"}
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired as exc:
        return 124, _text(exc.stdout), _text(exc.stderr) + f"\n(timed out after {timeout}s)"
    return done.returncode, done.stdout, done.stderr


def _text(data: str | bytes | None) -> str:
    if data is None:
        return ""
    return data.decode(errors="replace") if isinstance(data, bytes) else data


def evaluate(
    check: Check, code: int, stdout: str, stderr: str, workspace: Path, shown: set[str] | None = None
) -> CheckResult:
    """Decide whether one check passed.

    Args:
        check: The check.
        code: Bazel's exit code (0 for file-only checks).
        stdout: Bazel's standard output.
        stderr: Bazel's standard error.
        workspace: The staged workspace (for file assertions).
        shown: ERROR lines already reported by earlier checks; they are not repeated.

    Returns:
        The result, with the first failing reason.
    """
    output = stdout + stderr
    problems: list[str] = []
    if check.expect == "success" and code != 0:
        problems.append(f"expected the command to succeed, but it exited with code {code}")
    if check.expect == "failure" and code == 0:
        problems.append("expected the command to fail, but it succeeded")
    problems += [f"stdout lacks {s!r}" for s in check.stdout_contains if s not in stdout]
    problems += [f"stdout should not contain {s!r}" for s in check.stdout_lacks if s in stdout]
    if check.stdout_equals is not None and stdout.strip() != check.stdout_equals.strip():
        problems.append(f"stdout was {stdout.strip()!r}, expected {check.stdout_equals.strip()!r}")
    if check.stdout_lines is not None:
        got = {line.strip() for line in stdout.splitlines() if line.strip()}
        want = set(check.stdout_lines)
        if got != want:
            missing, extra = sorted(want - got), sorted(got - want)
            problems.append(f"output lines differ: missing {missing}, unexpected {extra}")
    problems += [f"output lacks {s!r}" for s in check.output_contains if s not in output]
    problems += [f"output should not contain {s!r}" for s in check.output_lacks if s in output]
    problems += [f"output does not match /{p}/" for p in check.output_matches if not re.search(p, output, re.M)]
    for rel in check.file_exists:
        if not (workspace / rel).exists():
            problems.append(f"{rel} does not exist")
    for rel, needle in check.file_contains.items():
        target = workspace / rel
        if not target.is_file() or needle not in target.read_text(encoding="utf-8", errors="replace"):
            problems.append(f"{rel} does not contain {needle!r}")
    if not problems:
        return CheckResult(check.name, True)
    detail = problems[0]
    if check.message:
        detail += f" — {check.message}"
    prefix = f"{workspace}/"
    errors = [line.replace(prefix, "") for line in output.splitlines() if line.startswith("ERROR:")]
    if shown is not None:
        fresh = [e for e in errors if e not in shown]
        shown.update(errors)
        errors = fresh
    if errors and code != 0:
        detail += "\n      " + "\n      ".join(errors[:4])
    return CheckResult(check.name, False, detail)


def grade_lab(
    root: Path, lab: Lab, *, source: Source | None = None, runner: Runner | None = None, on_result: Callable[[CheckResult], None] | None = None
) -> list[CheckResult]:
    """Run every check of a lab against the chosen workspace with real Bazel.

    Args:
        root: Repository root.
        lab: The lab.
        source: Which workspace to grade; see :func:`resolve_source`.
        runner: Runs a command and returns ``(code, stdout, stderr)``; defaults to a subprocess.
        on_result: Called with each result as soon as it is known.

    Returns:
        One result per check, in order.
    """
    chosen, _ = resolve_source(root, lab, source)
    checks = load_checks(lab)
    staged = stage_lab(root, lab, chosen)
    run = runner or _run
    bazel = find_bazel() if runner is None else "bazel"
    results: list[CheckResult] = []
    shown: set[str] = set()
    for check in checks:
        if check.command:
            # A short server idle time keeps many staged workspaces from holding memory after grading.
            code, out, err = run([bazel, "--max_idle_secs=120", *check.command], staged, lab.timeout)
        else:
            code, out, err = 0, "", ""
        result = evaluate(check, code, out, err, staged, shown)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results
