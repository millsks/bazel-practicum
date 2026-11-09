import shutil
import subprocess
from pathlib import Path

import pytest

from practicum import labs
from practicum.labs import (
    Check,
    CheckResult,
    LabError,
    Source,
    discover_labs,
    evaluate,
    find_bazel,
    get_lab,
    grade_lab,
    load_checks,
    load_lab,
    resolve_source,
    stage_lab,
    start_lab,
)


def test_load_lab_reads_fields(fake_repo: Path) -> None:
    lab = load_lab(fake_repo / "labs" / "m01-lab1")
    assert (lab.id, lab.title, lab.module, lab.timeout) == ("m01-lab1", "Demo lab", "m01", 60)
    assert lab.starter_dir.name == "starter"
    assert lab.solution_dir.name == "solution"
    assert lab.grading_dir.name == "grading"
    assert lab.work_dir(fake_repo) == fake_repo / "work" / "m01-lab1"


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (None, "missing"),
        ("id = ", "invalid TOML"),
        ('id = "x"\ntitle = "t"\n', "missing key 'module'"),
    ],
)
def test_load_lab_errors(tmp_path: Path, text: str | None, error: str) -> None:
    if text is not None:
        (tmp_path / "lab.toml").write_text(text, encoding="utf-8")
    with pytest.raises(LabError, match=error):
        load_lab(tmp_path)


def test_load_lab_default_timeout(tmp_path: Path) -> None:
    (tmp_path / "lab.toml").write_text('id = "a"\ntitle = "b"\nmodule = "m02"\n', encoding="utf-8")
    assert load_lab(tmp_path).timeout == 900


def test_load_checks_parses_every_key(fake_repo: Path) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    (lab.path / "checks.toml").write_text(
        """
[[check]]
name = "all keys"
command = ["test", "//..."]
expect = "any"
stdout_contains = ["a"]
stdout_lacks = ["b"]
stdout_equals = "c"
stdout_lines = ["d", "e"]
output_contains = ["f"]
output_lacks = ["g"]
output_matches = ["h+"]
message = "m"
file_exists = ["x"]
file_contains = {"y" = "z"}

[[check]]
name = "file only"
file_contains = {"a.txt" = "b"}
""",
        encoding="utf-8",
    )
    first, second = load_checks(lab)
    assert first == Check(
        name="all keys",
        command=("test", "//..."),
        expect="any",
        stdout_contains=("a",),
        stdout_lacks=("b",),
        stdout_equals="c",
        stdout_lines=("d", "e"),
        output_contains=("f",),
        output_lacks=("g",),
        output_matches=("h+",),
        message="m",
        file_exists=("x",),
        file_contains={"y": "z"},
    )
    assert second.command == ()
    assert second.stdout_lines is None
    assert second.expect == "success"


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (None, "missing"),
        ("[[check]\n", "invalid TOML"),
        ("title = 1\n", "at least one"),
        ('[[check]]\nname = "x"\ncommand = ["build"]\nbogus = 1\n', "unknown keys: bogus"),
        ('[[check]]\ncommand = ["build"]\n', "has no name"),
        ('[[check]]\nname = "x"\ncommand = ["build"]\nexpect = "maybe"\n', "expect must be"),
        ('[[check]]\nname = "x"\n', "no command and no file assertions"),
    ],
)
def test_load_checks_errors(fake_repo: Path, text: str | None, error: str) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    checks = lab.path / "checks.toml"
    if text is None:
        checks.unlink()
    else:
        checks.write_text(text, encoding="utf-8")
    with pytest.raises(LabError, match=error):
        load_checks(lab)


def test_discover_and_get_lab(fake_repo: Path) -> None:
    other = fake_repo / "labs" / "a-first"
    other.mkdir()
    (other / "lab.toml").write_text('id = "a0"\ntitle = "A"\nmodule = "m00"\n', encoding="utf-8")
    assert [lab.id for lab in discover_labs(fake_repo)] == ["a0", "m01-lab1"]
    assert get_lab(fake_repo, "a-first").id == "a0"  # directory name works too
    with pytest.raises(LabError, match="unknown lab 'nope'"):
        get_lab(fake_repo, "nope")


def test_start_lab_copies_starter_and_respects_force(fake_repo: Path) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    work = start_lab(fake_repo, lab)
    assert (work / "app" / "BUILD.bazel").read_text(encoding="utf-8") == "# TODO\n"
    assert not (work / "bazel-out").exists()
    (work / "app" / "BUILD.bazel").write_text("edited", encoding="utf-8")
    with pytest.raises(LabError, match="already exists"):
        start_lab(fake_repo, lab)
    start_lab(fake_repo, lab, force=True)
    assert (work / "app" / "BUILD.bazel").read_text(encoding="utf-8") == "# TODO\n"


def test_resolve_source_prefers_work(fake_repo: Path) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    assert resolve_source(fake_repo, lab, None) == (Source.STARTER, lab.starter_dir)
    start_lab(fake_repo, lab)
    assert resolve_source(fake_repo, lab, None) == (Source.WORK, lab.work_dir(fake_repo))
    assert resolve_source(fake_repo, lab, Source.SOLUTION) == (Source.SOLUTION, lab.solution_dir)


def test_stage_lab_overlays_grading_files(fake_repo: Path) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    staged = stage_lab(fake_repo, lab, Source.SOLUTION)
    assert staged == fake_repo / "build" / "labs" / "m01-lab1-solution"
    assert (staged / "grade" / "BUILD.bazel").is_file()
    assert (staged / "app" / "hello.py").is_file()
    (staged / "stale.txt").write_text("old", encoding="utf-8")
    assert not (stage_lab(fake_repo, lab, Source.SOLUTION) / "stale.txt").exists()


def test_stage_lab_without_grading_dir(fake_repo: Path) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    for path in sorted(lab.grading_dir.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    lab.grading_dir.rmdir()
    staged = stage_lab(fake_repo, lab, Source.STARTER)
    assert not (staged / "grade").exists()


def test_stage_lab_requires_module_bazel(fake_repo: Path) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    (lab.starter_dir / "MODULE.bazel").unlink()
    with pytest.raises(LabError, match=r"has no MODULE\.bazel"):
        stage_lab(fake_repo, lab, Source.STARTER)


def test_find_bazel_prefers_bazelisk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}" if name == "bazelisk" else None)
    assert find_bazel() == "/bin/bazelisk"
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/bazel" if name == "bazel" else None)
    assert find_bazel() == "/bin/bazel"
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(LabError, match="bazelisk not found"):
        find_bazel()


# ---------------------------------------------------------------------------------------------- evaluate


def _eval(check: Check, code: int = 0, out: str = "", err: str = "", ws: Path = Path("/ws")) -> CheckResult:
    return evaluate(check, code, out, err, ws)


def test_evaluate_success_and_failure_expectations() -> None:
    assert _eval(Check("ok")).ok
    assert _eval(Check("fails"), code=1).detail == "expected the command to succeed, but it exited with code 1"
    assert _eval(Check("x", expect="failure")).detail == "expected the command to fail, but it succeeded"
    assert _eval(Check("x", expect="failure"), code=1).ok
    assert _eval(Check("x", expect="any"), code=3).ok


def test_evaluate_stdout_assertions() -> None:
    assert _eval(Check("x", stdout_contains=("hi",)), out="hi there").ok
    assert _eval(Check("x", stdout_contains=("hi",)), err="hi").detail == "stdout lacks 'hi'"
    assert _eval(Check("x", stdout_lacks=("bad",)), out="bad").detail == "stdout should not contain 'bad'"
    assert _eval(Check("x", stdout_equals="Hello"), out="\nHello\n").ok
    assert _eval(Check("x", stdout_equals="Hello"), out="Hi").detail == "stdout was 'Hi', expected 'Hello'"


def test_evaluate_stdout_lines_is_order_insensitive() -> None:
    check = Check("x", stdout_lines=("//a:b", "//a:c"))
    assert _eval(check, out="//a:c\n\n  //a:b\n").ok
    result = _eval(check, out="//a:b\n//a:d\n")
    assert result.detail == "output lines differ: missing ['//a:c'], unexpected ['//a:d']"


def test_evaluate_output_assertions_cover_stderr() -> None:
    assert _eval(Check("x", output_contains=("not visible",)), err="ERROR: not visible").ok
    assert _eval(Check("x", output_contains=("zzz",))).detail == "output lacks 'zzz'"
    assert _eval(Check("x", output_lacks=("WARN",)), err="WARN").detail == "output should not contain 'WARN'"
    assert _eval(Check("x", output_matches=(r"^Executed \d+ out",)), err="x\nExecuted 2 out of 2").ok
    assert _eval(Check("x", output_matches=("^nope$",))).detail == "output does not match /^nope$/"


def test_evaluate_file_assertions(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("generated data", encoding="utf-8")
    assert evaluate(Check("x", file_exists=("out.txt",)), 0, "", "", tmp_path).ok
    assert evaluate(Check("x", file_exists=("gone",)), 0, "", "", tmp_path).detail == "gone does not exist"
    assert evaluate(Check("x", file_contains={"out.txt": "data"}), 0, "", "", tmp_path).ok
    bad = evaluate(Check("x", file_contains={"out.txt": "nope", "gone": "x"}), 0, "", "", tmp_path)
    assert bad.detail == "out.txt does not contain 'nope'"


def test_evaluate_adds_message_and_error_lines(tmp_path: Path) -> None:
    err = "\n".join(
        [
            "INFO: noise",
            f"ERROR: {tmp_path}/app/BUILD.bazel:1:1: name 'py_binary' is not defined",
            "ERROR: e2",
            "ERROR: e3",
            "ERROR: e4",
            "ERROR: e5",
        ]
    )
    result = evaluate(Check("x", message="Load the rule."), 1, "", err, tmp_path)
    lines = result.detail.splitlines()
    assert lines[0] == "expected the command to succeed, but it exited with code 1 — Load the rule."
    assert lines[1].strip() == "ERROR: app/BUILD.bazel:1:1: name 'py_binary' is not defined"
    assert len(lines) == 5  # at most four ERROR lines


def test_evaluate_does_not_repeat_shown_errors() -> None:
    shown: set[str] = set()
    first = evaluate(Check("a"), 1, "", "ERROR: same", Path("/ws"), shown)
    second = evaluate(Check("b"), 1, "", "ERROR: same\nERROR: new", Path("/ws"), shown)
    assert "ERROR: same" in first.detail
    assert "ERROR: same" not in second.detail
    assert "ERROR: new" in second.detail
    assert shown == {"ERROR: same", "ERROR: new"}


def test_evaluate_omits_error_lines_when_command_succeeded() -> None:
    result = evaluate(Check("x", stdout_contains=("y",)), 0, "", "ERROR: a warning-ish line", Path("/ws"))
    assert result.detail == "stdout lacks 'y'"


# --------------------------------------------------------------------------------------------- grade_lab


def test_grade_lab_with_injected_runner(fake_repo: Path) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    calls: list[tuple[list[str], Path, int]] = []
    seen: list[CheckResult] = []

    def runner(command: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
        calls.append((command, cwd, timeout))
        return 0, "Hello\n", ""

    results = grade_lab(fake_repo, lab, source=Source.SOLUTION, runner=runner, on_result=seen.append)
    assert results == [CheckResult("the app runs", True), CheckResult("the overlay is present", True)]
    assert seen == results
    assert calls == [
        (["bazel", "--max_idle_secs=120", "run", "//app:hello"], fake_repo / "build" / "labs" / "m01-lab1-solution", 60)
    ]


def test_grade_lab_reports_failures(fake_repo: Path) -> None:
    lab = get_lab(fake_repo, "m01-lab1")

    def runner(command: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
        return 1, "", f"ERROR: {cwd}/app/BUILD.bazel:1:1: no such target"

    first, _ = grade_lab(fake_repo, lab, runner=runner)
    assert not first.ok
    assert "Add a py_binary." in first.detail
    assert "ERROR: app/BUILD.bazel:1:1: no such target" in first.detail


def test_grade_lab_default_runner_uses_find_bazel(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = get_lab(fake_repo, "m01-lab1")
    seen: list[list[str]] = []
    monkeypatch.setattr(labs, "find_bazel", lambda: "/opt/bazelisk")

    def fake_run(command: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
        seen.append(command)
        return 0, "Hello", ""

    monkeypatch.setattr(labs, "_run", fake_run)
    assert all(r.ok for r in grade_lab(fake_repo, lab, source=Source.SOLUTION))
    assert seen[0][0] == "/opt/bazelisk"


def test_run_strips_java_tool_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Xmx1m")
    code, out, err = labs._run(["sh", "-c", 'echo "[$JAVA_TOOL_OPTIONS]"; echo oops >&2; exit 3'], tmp_path, 30)
    assert (code, out, err) == (3, "[]\n", "oops\n")


def test_run_reports_timeouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="bazel", timeout=5, output=b"partial", stderr=None)

    monkeypatch.setattr(subprocess, "run", slow)
    code, out, err = labs._run(["bazel"], tmp_path, 5)
    assert code == 124
    assert out == "partial"
    assert err == "\n(timed out after 5s)"


def test_text_decodes_bytes_and_none() -> None:
    assert labs._text(None) == ""
    assert labs._text(b"caf\xc3\xa9 \xff") == "café �"
    assert labs._text("s") == "s"
