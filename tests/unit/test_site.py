import json
from pathlib import Path

import pytest

from practicum.site import check_site, load_curriculum, registered_visualizers, scan_page, validate_quiz
from tests.conftest import page, write_manifest


def quiz(questions: list[dict[str, object]]) -> str:
    return json.dumps({"questions": questions})


GOOD_SINGLE = {"type": "single", "prompt": "p", "options": ["a", "b"], "answer": 1, "explanation": "e"}


def test_validate_quiz_accepts_every_type() -> None:
    questions = [
        GOOD_SINGLE,
        {"type": "multi", "prompt": "p", "options": ["a", "b", "c"], "answer": [0, 2], "explanation": "e"},
        {"type": "output", "prompt": "p", "answer": "1\n2", "explanation": "e"},
        {"type": "text", "prompt": "p", "answer": ["def", "DEF"], "explanation": "e"},
        {"prompt": "default type is single", "options": ["a", "b"], "answer": 0, "explanation": "e"},
    ]
    assert validate_quiz(quiz(questions)) == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("{not json", "invalid JSON"),
        ("[]", "non-empty 'questions'"),
        (quiz([]), "non-empty 'questions'"),
        (quiz(["oops"]), "must be an object"),
        (quiz([{**GOOD_SINGLE, "type": "essay"}]), "unknown type 'essay'"),
        (quiz([{**GOOD_SINGLE, "explanation": ""}]), "missing 'explanation'"),
        (quiz([{**GOOD_SINGLE, "options": ["only"]}]), "at least two 'options'"),
        (quiz([{**GOOD_SINGLE, "answer": 5}]), "valid option indexes"),
        (quiz([{**GOOD_SINGLE, "answer": True}]), "valid option indexes"),
        (quiz([{**GOOD_SINGLE, "type": "multi", "answer": []}]), "non-empty list"),
        (quiz([{"type": "output", "prompt": "p", "answer": 3, "explanation": "e"}]), "string or list"),
    ],
)
def test_validate_quiz_reports_problems(payload: str, expected: str) -> None:
    problems = validate_quiz(payload)
    assert any(expected in p for p in problems), problems


def test_scan_page_collects_everything() -> None:
    html = page(
        """
        <body data-module="m05"><div id="top"></div><a href="#top">x</a><img src="a.png"><br>
        <div class="quiz" data-id="q1"><script type="application/json">{"questions": []}</script></div>
        <div class="exercise" data-id="e1"><p>x</p><script type="text/x-python" class="tests">def test_a(bazel): pass</script></div>
        <div class="exercise" data-id="e2"><p>no tests</p></div>
        <div class="viz" data-viz="phases"></div>
        <div class="lab" data-id="m05-lab1"></div><span class="lab" data-id="ignored"></span>
        """
    )
    scan = scan_page(html)
    assert scan.title == "Page"
    assert scan.module_id == "m05"
    assert {"#top", "a.png"} <= set(scan.links)
    assert "top" in scan.ids
    assert scan.quizzes == [("q1", '{"questions": []}')]
    assert scan.exercises == [("e1", True), ("e2", False)]
    assert scan.viz == ["phases"]
    assert scan.labs == ["m05-lab1"]


def build_site(tmp_path: Path) -> Path:
    site = tmp_path / "docs"
    write_manifest(
        site,
        [
            {
                "id": "p1",
                "modules": [{"id": "m01", "href": "modules/m01.html"}, {"id": "m02", "href": "modules/gone.html"}],
                "projects": [{"id": "p01", "href": "projects/p01.html"}],
            }
        ],
        reference=[{"id": "r", "href": "reference/r.html"}],
    )
    (site / "assets" / "js" / "viz.js").write_text('registerViz("sorting", () => {});', encoding="utf-8")
    (site / "assets" / "js" / "viz-extra.js").write_text("PPViz.registerViz('graph', f);", encoding="utf-8")
    (site / "modules").mkdir()
    (site / "projects").mkdir()
    for lab in ("m01-lab1", "orphan-lab"):
        (tmp_path / "labs" / lab).mkdir(parents=True)
        (tmp_path / "labs" / lab / "lab.toml").write_text("", encoding="utf-8")
    (site / "modules" / "m01.html").write_text(
        page(
            """
            <a href="../projects/p01.html#ok">good</a><a href="../projects/p01.html">good</a>
            <a href="missing.html">bad</a><a href="#nowhere">bad anchor</a><a href="https://example.com">ext</a>
            <a href="../../outside.html">escape</a><a href="../modules/">dir</a>
            <div class="quiz" data-id="m01-quiz"><script type="application/json">{"questions": [{"prompt": "x"}]}</script></div>
            <div class="exercise" data-id="m01-e1"><script class="tests">def test(): pass</script></div>
            <div class="exercise"><script class="tests">x</script></div>
            <div class="viz" data-viz="graph"></div><div class="viz" data-viz="mystery"></div>
            <div class="lab" data-id="m01-lab1"></div><div class="lab" data-id="m09-lab7"></div><div class="lab"></div>
            """
        ),
        encoding="utf-8",
    )
    (site / "projects" / "p01.html").write_text(
        "<html><body><div id='ok'></div><div class='exercise' data-id='m01-e1'>"
        "<p>dup without tests</p></div></body></html>",
        encoding="utf-8",
    )
    return site


def test_check_site_finds_every_problem(tmp_path: Path) -> None:
    messages = {(i.path, i.message) for i in check_site(build_site(tmp_path))}
    assert ("assets/js/curriculum.js", "manifest page does not exist: modules/gone.html") in messages
    assert ("assets/js/curriculum.js", "manifest page does not exist: reference/r.html") in messages
    assert ("modules/m01.html", "broken link: missing.html") in messages
    assert ("modules/m01.html", "missing anchor #nowhere") in messages
    assert ("modules/m01.html", "link escapes the site: ../../outside.html") in messages
    assert ("modules/m01.html", "broken link: ../modules/") in messages
    assert ("modules/m01.html", "exercise without data-id") in messages
    assert ("modules/m01.html", "unknown visualizer 'mystery'") in messages
    assert any(p == "modules/m01.html" and m.startswith("quiz m01-quiz: question 1") for p, m in messages)
    assert ("projects/p01.html", "page has no <title>") in messages
    assert ("projects/p01.html", "exercise id m01-e1 also used in modules/m01.html") in messages
    assert ("projects/p01.html", "exercise m01-e1 has no tests script") in messages
    assert ("modules/m01.html", "lab m09-lab7 has no labs/m09-lab7/lab.toml") in messages
    assert ("modules/m01.html", "lab without data-id") in messages
    assert ("../labs/orphan-lab", "lab is not introduced by any page") in messages
    assert not any("m01-lab1" in m for _, m in messages)
    assert not any("example.com" in m or ("p01.html" in m and "broken" in m) for _, m in messages)


def test_check_site_reports_bad_manifest(tmp_path: Path) -> None:
    (tmp_path / "assets" / "js").mkdir(parents=True)
    (tmp_path / "assets" / "js" / "curriculum.js").write_text("window.CURRICULUM = {broken};", encoding="utf-8")
    issues = check_site(tmp_path)
    assert len(issues) == 1
    assert "not valid JSON" in issues[0].message


def test_load_curriculum_requires_object(tmp_path: Path) -> None:
    (tmp_path / "assets" / "js").mkdir(parents=True)
    (tmp_path / "assets" / "js" / "curriculum.js").write_text("// empty", encoding="utf-8")
    with pytest.raises(ValueError, match="does not contain"):
        load_curriculum(tmp_path)


def test_registered_visualizers_scans_all_viz_files(tmp_path: Path) -> None:
    site = build_site(tmp_path)
    assert registered_visualizers(site) == {"sorting", "graph"}
    assert registered_visualizers(tmp_path / "nothing") == set()


def test_check_site_accepts_the_minimal_fake_repo(fake_repo: Path) -> None:
    assert check_site(fake_repo / "docs") == []


def test_check_site_ignores_malformed_manifest_entries(tmp_path: Path) -> None:
    js = tmp_path / "assets" / "js"
    js.mkdir(parents=True)
    (js / "curriculum.js").write_text(
        'window.CURRICULUM = {"parts": ["x", {"modules": ["y", {"href": 3}]}], "reference": "z"};', encoding="utf-8"
    )
    assert check_site(tmp_path) == []
