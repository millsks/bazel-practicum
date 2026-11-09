from pathlib import Path
from typing import Any

import pytest

from practicum import cli
from practicum.exercises import ExerciseResult
from practicum.labs import CheckResult, Lab, Source
from practicum.workspace import ROOT_ENV_VAR


@pytest.fixture(autouse=True)
def in_repo(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(ROOT_ENV_VAR, str(fake_repo))
    return fake_repo


def fake_grader(outcomes: dict[Source, list[bool]], calls: list[tuple[str, Source | None]] | None = None) -> Any:
    def grade(
        root: Path, lab: Lab, *, source: Source | None = None, runner: Any = None, on_result: Any = None
    ) -> list[CheckResult]:
        if calls is not None:
            calls.append((lab.id, source))
        results = [
            CheckResult(f"check {i}", ok, "" if ok else "it failed")
            for i, ok in enumerate(outcomes[source or Source.STARTER])
        ]
        for result in results:
            if on_result is not None:
                on_result(result)
        return results

    return grade


def test_labs_lists_each_lab(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["labs"]) == 0
    err = capsys.readouterr().err
    assert "id=m01-lab1" in err
    assert "started=False" in err


def test_start_then_restart_without_force(in_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["start", "m01-lab1"]) == 0
    assert (in_repo / "work" / "m01-lab1" / "MODULE.bazel").is_file()
    assert "work_dir=work/m01-lab1" in capsys.readouterr().err
    assert cli.main(["start", "m01-lab1"]) == 2
    assert "already exists" in capsys.readouterr().err
    assert cli.main(["start", "m01-lab1", "--force"]) == 0


def test_unknown_lab_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["grade", "m77-lab9"]) == 2
    assert "unknown lab" in capsys.readouterr().err


def test_missing_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(tmp_path_factory.mktemp("empty")))
    assert cli.main(["labs"]) == 2


def test_grade_starter_warns_and_prints_results(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, Source | None]] = []
    monkeypatch.setattr(cli, "grade_lab", fake_grader({Source.STARTER: [True, False]}, calls))
    assert cli.main(["grade", "m01-lab1"]) == 1
    captured = capsys.readouterr()
    assert "grading_starter" in captured.err
    assert "Demo lab" in captured.out
    assert "  ✓ check 0" in captured.out
    assert "  ✗ check 1\n      it failed" in captured.out
    assert "1/2 checks passed." in captured.out
    assert calls == [("m01-lab1", Source.STARTER)]


def test_grade_work_copy_passes(
    in_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["start", "m01-lab1"]) == 0
    monkeypatch.setattr(cli, "grade_lab", fake_grader({Source.WORK: [True, True]}))
    assert cli.main(["grade", "m01-lab1"]) == 0
    captured = capsys.readouterr()
    assert "2/2 checks passed. Lab complete." in captured.out
    assert "grading_starter" not in captured.err
    assert "source=work" in captured.err


def test_grade_explicit_source(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, Source | None]] = []
    monkeypatch.setattr(cli, "grade_lab", fake_grader({Source.SOLUTION: [True]}, calls))
    assert cli.main(["grade", "m01-lab1", "--source", "solution"]) == 0
    assert calls == [("m01-lab1", Source.SOLUTION)]
    assert "grading_starter" not in capsys.readouterr().err


def test_check_labs_all_good(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, Source | None]] = []
    monkeypatch.setattr(cli, "grade_lab", fake_grader({Source.SOLUTION: [True], Source.STARTER: [False]}, calls))
    assert cli.main(["check-labs"]) == 0
    assert calls == [("m01-lab1", Source.SOLUTION), ("m01-lab1", Source.STARTER)]
    assert "lab_ok" in capsys.readouterr().err


def test_check_labs_solution_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, Source | None]] = []
    monkeypatch.setattr(cli, "grade_lab", fake_grader({Source.SOLUTION: [False]}, calls))
    assert cli.main(["check-labs", "m01-lab1"]) == 1
    assert calls == [("m01-lab1", Source.SOLUTION)]
    assert "solution_check_failed" in capsys.readouterr().err


def test_check_labs_starter_must_fail(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "grade_lab", fake_grader({Source.SOLUTION: [True], Source.STARTER: [True]}))
    assert cli.main(["check-labs"]) == 1
    assert "starter_passes" in capsys.readouterr().err


def test_check_labs_solutions_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Source | None]] = []
    monkeypatch.setattr(cli, "grade_lab", fake_grader({Source.SOLUTION: [True], Source.STARTER: [True]}, calls))
    assert cli.main(["check-labs", "--solutions-only"]) == 0
    assert calls == [("m01-lab1", Source.SOLUTION)]


def test_serve_handles_interrupt(monkeypatch: pytest.MonkeyPatch, in_repo: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_serve(site_root: Path, host: str, port: int, *, open_browser: bool) -> None:
        seen.update(site_root=site_root, host=host, port=port, open_browser=open_browser)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "serve", fake_serve)
    assert cli.main(["serve", "--port", "9999", "--no-browser"]) == 0
    assert seen == {"site_root": in_repo / "docs", "host": "127.0.0.1", "port": 9999, "open_browser": False}


def test_check_site_clean_and_dirty(in_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check-site"]) == 0
    (in_repo / "docs" / "modules" / "m01.html").write_text(
        "<title>x</title><a href='nope.html'><div class='lab' data-id='m01-lab1'></div>", encoding="utf-8"
    )
    assert cli.main(["--json", "check-site"]) == 1
    assert "broken link: nope.html" in capsys.readouterr().err


def test_check_exercises_reports_failures(monkeypatch: pytest.MonkeyPatch, in_repo: Path) -> None:
    pages: list[Path] = []

    def fake_check(site_root: Path, page: Path) -> list[ExerciseResult]:
        pages.append(page)
        return [ExerciseResult("a", True), ExerciseResult("b", False, "boom")]

    monkeypatch.setattr(cli, "check_page", fake_check)
    assert cli.main(["check-exercises"]) == 1
    assert pages == [in_repo / "docs" / "modules" / "m01.html"]
    monkeypatch.setattr(cli, "check_page", lambda site_root, page: [ExerciseResult("a", True)])
    assert cli.main(["check-exercises", "docs/modules/m01.html"]) == 0


def test_check_exercises_on_the_fake_site(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check-exercises"]) == 0
    assert "total=0" in capsys.readouterr().err


def test_bundle_writes_file(in_repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_write(site_root: Path, out: Path) -> tuple[int, int]:
        out.write_text("x", encoding="utf-8")
        return 3, 1

    monkeypatch.setattr(cli, "write_bundle", fake_write)
    assert cli.main(["bundle", "--out", "single.html"]) == 0
    assert (in_repo / "single.html").read_text(encoding="utf-8") == "x"
    assert "pages=3" in capsys.readouterr().err


def test_bundle_failure_returns_one(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(site_root: Path, out: Path) -> tuple[int, int]:
        raise cli.BundleError("no manifest")

    monkeypatch.setattr(cli, "write_bundle", broken)
    assert cli.main(["bundle"]) == 1
    assert "no manifest" in capsys.readouterr().err


def test_parser_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        cli.main([])
