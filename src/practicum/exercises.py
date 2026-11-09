"""Verify in-page exercises and sandboxes against the Bazel simulator.

An exercise's reference solution must pass every check, and its starter must fail at least one (otherwise the
exercise asks for nothing). Every sandbox command must run without crashing the simulator.
"""

import json
import textwrap
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType

from practicum.sim import load_simulator

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"})


@dataclass
class Exercise:
    """An exercise extracted from a page.

    Attributes:
        id: The exercise ``data-id``.
        files: Starter workspace: path to content.
        tests: Python source of the ``test_*(bazel)`` check functions.
        solution: Files the reference solution replaces: path to content.
    """

    id: str
    files: dict[str, str] = field(default_factory=dict)
    tests: str = ""
    solution: dict[str, str] = field(default_factory=dict)


@dataclass
class Sandbox:
    """A runnable sandbox extracted from a page.

    Attributes:
        title: The sandbox title (for messages).
        files: Workspace files: path to content.
        commands: Suggested commands.
    """

    title: str
    files: dict[str, str] = field(default_factory=dict)
    commands: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExerciseResult:
    """Outcome of checking one exercise or sandbox.

    Attributes:
        id: The exercise id or sandbox title.
        ok: Whether it behaved as required.
        detail: Failure details; empty when ``ok``.
    """

    id: str
    ok: bool
    detail: str = ""


def _clean(source: str) -> str:
    text = textwrap.dedent(source.replace("\t", "    ")).strip("\n")
    return text + "\n" if text else ""


class _Parser(HTMLParser):
    """Collect exercises (files, tests, solution files) and sandboxes from one page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.exercises: list[Exercise] = []
        self.sandboxes: list[Sandbox] = []
        self._depth = 0
        self._widget: Exercise | Sandbox | None = None
        self._widget_depth = 0
        self._solution_depth: int | None = None
        self._capture: str | None = None
        self._path = ""
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        classes = set(a.get("class", "").split())
        if tag not in _VOID:
            self._depth += 1
        if self._widget is None:
            if "exercise" in classes and tag == "div":
                self._widget, self._widget_depth = Exercise(a.get("data-id", "")), self._depth
            elif "runnable" in classes and tag == "div":
                raw = a.get("data-commands") or a.get("data-command") or "bazel build //..."
                commands = [c.strip() for c in raw.split("|") if c.strip()]
                self._widget, self._widget_depth = Sandbox(a.get("data-title", "(untitled)"), {}, commands), self._depth
            return
        if tag == "textarea" and "file" in classes:
            self._capture, self._path, self._buffer = "file", a.get("data-path", ""), []
        elif tag == "script" and "tests" in classes:
            self._capture, self._buffer = "tests", []
        elif tag == "details" and "solution" in classes:
            self._solution_depth = self._depth
        elif tag == "pre" and self._solution_depth is not None and a.get("data-path"):
            self._path = a["data-path"]
        elif tag == "code" and self._solution_depth is not None and self._path:
            self._capture, self._buffer = "solution", []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        w = self._widget
        if w is not None and self._capture:
            text = "".join(self._buffer)
            if self._capture == "file" and tag == "textarea":
                w.files[self._path] = _clean(text)
                self._capture = None
            elif self._capture == "tests" and tag == "script" and isinstance(w, Exercise):
                w.tests = _clean(text)
                self._capture = None
            elif self._capture == "solution" and tag == "code" and isinstance(w, Exercise):
                w.solution[self._path] = _clean(text)
                self._capture, self._path = None, ""
        if self._solution_depth == self._depth and tag == "details":
            self._solution_depth = None
        if w is not None and self._depth == self._widget_depth and tag == "div":
            (self.exercises if isinstance(w, Exercise) else self.sandboxes).append(w)  # type: ignore[arg-type]
            self._widget = None
        if tag not in _VOID:
            self._depth -= 1


def extract(html: str) -> tuple[list[Exercise], list[Sandbox]]:
    """Extract every exercise and sandbox from a page.

    Args:
        html: Page source.

    Returns:
        Exercises and sandboxes in page order.
    """
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.exercises, parser.sandboxes


def run_checks(sim: ModuleType, files: dict[str, str], tests: str) -> list[dict[str, object]]:
    """Run check functions exactly as the browser does.

    Args:
        sim: The simulator module.
        files: Workspace files.
        tests: Check source.

    Returns:
        One ``{"name", "ok", "msg"}`` per check.
    """
    # Round-trip through JSON so the files reach the simulator in the same form the browser sends.
    results: list[dict[str, object]] = sim.run_checks(json.loads(json.dumps(files)), tests)
    return results


def check_exercise(sim: ModuleType, exercise: Exercise) -> ExerciseResult:
    """Require the reference solution to pass and the starter to fail.

    Args:
        sim: The simulator module.
        exercise: The exercise to check.

    Returns:
        The outcome.
    """
    if not exercise.tests.strip():
        return ExerciseResult(exercise.id, False, "no checks in a script.tests block")
    if not exercise.solution:
        return ExerciseResult(exercise.id, False, "no solution files (details.solution pre[data-path] > code)")
    unknown = sorted(set(exercise.solution) - set(exercise.files))
    if unknown:
        return ExerciseResult(exercise.id, False, f"solution edits files the starter lacks: {', '.join(unknown)}")
    try:
        solved = run_checks(sim, {**exercise.files, **exercise.solution}, exercise.tests)
        starter = run_checks(sim, exercise.files, exercise.tests)
    except Exception as exc:
        return ExerciseResult(exercise.id, False, f"checks raised {type(exc).__name__}: {exc}")
    if not solved:
        return ExerciseResult(exercise.id, False, "no test_* functions in the checks")
    failures = [f"{r['name']}: {r['msg']}" for r in solved if not r["ok"]]
    if failures:
        return ExerciseResult(exercise.id, False, "solution fails: " + "; ".join(failures))
    if all(r["ok"] for r in starter):
        return ExerciseResult(exercise.id, False, "the starter already passes every check")
    return ExerciseResult(exercise.id, True)


def check_sandbox(sim: ModuleType, sandbox: Sandbox) -> ExerciseResult:
    """Run each suggested command; the simulator may report Bazel errors but must not crash.

    Args:
        sim: The simulator module.
        sandbox: The sandbox to check.

    Returns:
        The outcome.
    """
    for command in sandbox.commands:
        try:
            sim.Bazel(dict(sandbox.files)).run_command(command)
        except Exception as exc:
            return ExerciseResult(sandbox.title, False, f"`{command}` crashed: {type(exc).__name__}: {exc}")
    return ExerciseResult(sandbox.title, True)


def check_page(site_root: Path, page: Path) -> list[ExerciseResult]:
    """Check every exercise and sandbox on one page.

    Args:
        site_root: The ``docs/`` directory (where the simulator lives).
        page: HTML file to check.

    Returns:
        One result per exercise and sandbox.
    """
    sim = load_simulator(site_root)
    exercises, sandboxes = extract(page.read_text(encoding="utf-8"))
    return [*(check_exercise(sim, e) for e in exercises), *(check_sandbox(sim, s) for s in sandboxes)]
