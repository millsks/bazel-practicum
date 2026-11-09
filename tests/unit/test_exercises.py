from pathlib import Path
from types import ModuleType

from practicum.exercises import (
    Exercise,
    Sandbox,
    check_exercise,
    check_page,
    check_sandbox,
    extract,
    run_checks,
)
from tests.conftest import page

MODULE = 'module(name = "demo")\nbazel_dep(name = "rules_python", version = "2.4.6")\n'
GOOD_BUILD = 'load("@rules_python//python:defs.bzl", "py_binary")\npy_binary(name = "hello", srcs = ["hello.py"])\n'
TESTS = """
def test_hello_is_a_binary(bazel):
    assert bazel.target("//app:hello").kind == "py_binary", "make //app:hello a py_binary"
"""

HTML = """
<div class="exercise" data-id="m01-e1" data-title="T">
  <div class="exercise-prompt"><p>Do it &amp; win</p></div>
<textarea class="file" data-path="MODULE.bazel" data-readonly>
module(name = "demo")
bazel_dep(name = "rules_python", version = "2.4.6")
</textarea>
<textarea class="file" data-path="app/BUILD.bazel">
	# a tab-indented comment &lt;here&gt;
</textarea>
<textarea class="file" data-path="app/hello.py" data-hidden></textarea>
<script type="text/x-python" class="tests">
    def test_hello_is_a_binary(bazel):
        assert bazel.target("//app:hello").kind == "py_binary", "make //app:hello a py_binary"
</script>
  <details class="hint"><summary>Hint</summary><pre data-path="app/BUILD.bazel"><code>not the solution</code></pre></details>
  <details class="solution"><summary>Show</summary>
<pre data-path="app/BUILD.bazel"><code class="language-starlark">load("@rules_python//python:defs.bzl", "py_binary")
py_binary(name = "hello", srcs = ["hello.py"])</code></pre>
<pre data-label="Terminal"><code>bazel build //app:hello</code></pre>
  </details>
</div>
<div class="runnable" data-title="Sandbox" data-commands="bazel query //...| bazel build //app:hello |">
<textarea class="file" data-path="MODULE.bazel">module(name = "demo")</textarea>
<br>
</div>
<div class="runnable"><textarea class="file" data-path="MODULE.bazel"></textarea></div>
<div class="runnable" data-command="bazel version"></div>
"""


def test_extract_reads_files_tests_solution_and_sandboxes() -> None:
    exercises, sandboxes = extract(HTML)
    (ex,) = exercises
    assert ex.id == "m01-e1"
    assert ex.files["MODULE.bazel"].startswith('module(name = "demo")\n')
    assert ex.files["app/BUILD.bazel"] == "# a tab-indented comment <here>\n"
    assert ex.files["app/hello.py"] == ""
    assert ex.tests.startswith("def test_hello_is_a_binary(bazel):\n    assert")
    assert ex.solution == {"app/BUILD.bazel": GOOD_BUILD}
    assert [s.title for s in sandboxes] == ["Sandbox", "(untitled)", "(untitled)"]
    assert sandboxes[0].commands == ["bazel query //...", "bazel build //app:hello"]
    assert sandboxes[1].commands == ["bazel build //..."]
    assert sandboxes[2].commands == ["bazel version"]


def test_run_checks_reports_each_check(mb: ModuleType) -> None:
    results = run_checks(mb, {"MODULE.bazel": MODULE, "app/BUILD.bazel": GOOD_BUILD, "app/hello.py": ""}, TESTS)
    assert results == [{"name": "hello is a binary", "ok": True, "msg": ""}]


def _exercise(**changes: object) -> Exercise:
    ex = Exercise(
        "e1",
        {"MODULE.bazel": MODULE, "app/BUILD.bazel": "", "app/hello.py": ""},
        TESTS,
        {"app/BUILD.bazel": GOOD_BUILD},
    )
    for key, value in changes.items():
        setattr(ex, key, value)
    return ex


def test_check_exercise_passes_a_valid_exercise(mb: ModuleType) -> None:
    assert check_exercise(mb, _exercise()).ok


def test_check_exercise_requires_tests_and_solution(mb: ModuleType) -> None:
    assert "no checks" in check_exercise(mb, _exercise(tests="  \n")).detail
    assert "no solution files" in check_exercise(mb, _exercise(solution={})).detail


def test_check_exercise_rejects_solution_for_unknown_file(mb: ModuleType) -> None:
    result = check_exercise(mb, _exercise(solution={"other/BUILD.bazel": "x"}))
    assert result.detail == "solution edits files the starter lacks: other/BUILD.bazel"


def test_check_exercise_reports_broken_check_source(mb: ModuleType) -> None:
    result = check_exercise(mb, _exercise(tests="def test_x(bazel):\n  return (\n"))
    assert "checks raised SyntaxError" in result.detail


def test_check_exercise_needs_test_functions(mb: ModuleType) -> None:
    assert check_exercise(mb, _exercise(tests="x = 1\n")).detail == "no test_* functions in the checks"


def test_check_exercise_reports_failing_solution(mb: ModuleType) -> None:
    result = check_exercise(mb, _exercise(solution={"app/BUILD.bazel": "# nothing\n"}))
    assert not result.ok
    assert result.detail.startswith("solution fails: hello is a binary: Bazel reported an error: no such target")


def test_check_exercise_rejects_a_starter_that_already_passes(mb: ModuleType) -> None:
    files = {"MODULE.bazel": MODULE, "app/BUILD.bazel": GOOD_BUILD, "app/hello.py": ""}
    result = check_exercise(mb, _exercise(files=files))
    assert result.detail == "the starter already passes every check"


def test_check_sandbox_runs_every_command(mb: ModuleType) -> None:
    sandbox = Sandbox("s", {"MODULE.bazel": MODULE}, ["bazel query //...", "bazel version"])
    assert check_sandbox(mb, sandbox).ok


def test_check_sandbox_reports_crashes() -> None:
    class Boom:
        def __init__(self, files: dict[str, str]) -> None:
            pass

        def run_command(self, command: str) -> None:
            raise RuntimeError("kaboom")

    fake = ModuleType("fake")
    fake.Bazel = Boom  # type: ignore[attr-defined]
    result = check_sandbox(fake, Sandbox("s", {}, ["bazel build //..."]))
    assert not result.ok
    assert result.detail == "`bazel build //...` crashed: RuntimeError: kaboom"


def test_check_page_checks_exercises_and_sandboxes(fake_repo: Path) -> None:
    target = fake_repo / "docs" / "modules" / "ex.html"
    target.write_text(page(HTML), encoding="utf-8")
    results = check_page(fake_repo / "docs", target)
    assert [(r.id, r.ok) for r in results] == [
        ("m01-e1", True),
        ("Sandbox", True),
        ("(untitled)", True),
        ("(untitled)", True),
    ]
