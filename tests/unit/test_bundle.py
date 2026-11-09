import json
import re
from pathlib import Path

import pytest

from practicum import bundle
from practicum.bundle import (
    BundleError,
    build_bundle,
    collect_pages,
    extract_main,
    fill_template,
    read_page,
    write_bundle,
)
from practicum.site import load_curriculum
from tests.conftest import page, write_manifest

MODULE_BODY = """
<main class="lesson">
  <header class="lesson-hero"><h1>Functions</h1></header>
  <section class="lesson-section" id="practice">
    <div class="exercise" data-id="m01-e1"><textarea class="file" data-path="BUILD.bazel">x = 1</textarea></div>
    <div class="exercise" data-id="m01-e2"><textarea class="file" data-path="BUILD.bazel">y = 2</textarea></div>
  </section>
  <section class="lesson-section" id="quiz"><div class="quiz" data-id="m01-quiz"></div></section>
  <section class="lesson-section" id="lab">
    <div class="lab" data-id="m01-lab1"></div>
    <ul class="checklist" data-id="m01-mini"><li>One <img src="a.png"><br/></li><li>Two <ul><li>nested</li></ul></li><li>Three</li></ul>
  </section>
</main>
"""


@pytest.fixture
def site(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    write_manifest(
        root,
        [
            {
                "id": "part1",
                "modules": [{"id": "m01", "href": "modules/m01.html"}],
                "projects": [{"id": "c1", "href": "projects/c1.html"}],
            }
        ],
        reference=[{"id": "ref-glossary", "href": "reference/glossary.html"}],
    )
    for href, body in {
        "index.html": "<main><h1>Home</h1></main>",
        "modules/m01.html": MODULE_BODY,
        "projects/c1.html": "<main><h1>Capstone</h1></main>",
        "reference/glossary.html": "<main><h1>Glossary</h1></main>",
    }.items():
        (root / href).parent.mkdir(parents=True, exist_ok=True)
        (root / href).write_text(page(body, title=f"{href} · T"), encoding="utf-8")
    js = root / "assets" / "js"
    for name in bundle.SCRIPT_ORDER:
        (js / name).write_text(f"window.loaded = {json.dumps(name)};\n", encoding="utf-8")
    (root / "assets" / "py").mkdir(parents=True)
    (root / "assets" / "py" / "minibazel.py").write_text('"""sim"""\nx = "<b>"\n', encoding="utf-8")
    (root / "assets" / "css").mkdir(parents=True)
    (root / "assets" / "css" / "course.css").write_text(
        '@import url("https://fonts.example/inter.css");\nbody { color: red; }\n', encoding="utf-8"
    )
    return root


def _data(html: str) -> dict[str, object]:
    match = re.search(r'<script type="application/json" id="pp-data">(.*?)</script>', html, re.S)
    assert match
    data: dict[str, object] = json.loads(match.group(1))
    return data


def test_extract_main_returns_inner_html() -> None:
    assert extract_main('<body><main class="x">\n<p>hi</p>\n</main></body>', "a.html") == "<p>hi</p>"


def test_extract_main_without_main_raises() -> None:
    with pytest.raises(BundleError, match=r"a\.html: no <main>"):
        extract_main("<body></body>", "a.html")


def test_read_page_counts_widgets(site: Path) -> None:
    result = read_page(site, "modules/m01.html", "m01", "module")
    assert result.title == "modules/m01.html · T"
    assert result.exercises == ("m01-e1", "m01-e2", "m01-lab1")
    assert result.quizzes == ("m01-quiz",)
    assert result.checklists == {"m01-mini": 3}
    assert result.html.startswith('<header class="lesson-hero">')


def test_read_page_missing_raises(site: Path) -> None:
    with pytest.raises(BundleError, match=r"does not exist"):
        read_page(site, "modules/nope.html", "m99", "module")


def test_collect_pages_covers_manifest_and_home(site: Path) -> None:
    pages = collect_pages(site, load_curriculum(site))
    assert {path: (p.id, p.kind) for path, p in pages.items()} == {
        "index.html": ("home", "home"),
        "modules/m01.html": ("m01", "module"),
        "projects/c1.html": ("c1", "project"),
        "reference/glossary.html": ("ref-glossary", "reference"),
    }


def test_collect_pages_rejects_duplicate_ids(site: Path) -> None:
    manifest: dict[str, object] = {"parts": [{"modules": [{"id": "m01", "href": "modules/m01.html"}], "projects": []}]}
    manifest["reference"] = [{"id": "m01", "href": "reference/glossary.html"}]
    with pytest.raises(BundleError, match="duplicate id"):
        collect_pages(site, manifest)


def test_collect_pages_ignores_malformed_entries(site: Path) -> None:
    manifest: dict[str, object] = {"parts": ["junk", {"modules": ["junk"], "projects": []}], "reference": "junk"}
    assert list(collect_pages(site, manifest)) == ["index.html"]


def test_fill_template_is_single_pass() -> None:
    assert fill_template("a @@X@@ b", {"X": "@@Y@@"}) == "a @@Y@@ b"


def test_fill_template_unknown_placeholder_raises() -> None:
    with pytest.raises(BundleError, match="NOPE"):
        fill_template("@@NOPE@@", {})


def test_build_bundle_embeds_pages_scripts_and_styles(site: Path) -> None:
    html, count = build_bundle(site)
    assert count == 4
    assert html.startswith("<!doctype html>")
    assert "<title>T</title>" in html
    assert "@import" not in html
    assert "body { color: red; }" in html
    order = [html.index(f'window.loaded = "{name}"') for name in bundle.SCRIPT_ORDER]
    assert order == sorted(order)
    assert html.index('window.loaded = "course.js"') < html.index("Single-file edition shell")
    data = _data(html)
    pages = data["pages"]
    assert isinstance(pages, dict)
    assert pages["modules/m01.html"]["exercises"] == ["m01-e1", "m01-e2", "m01-lab1"]
    assert "window.PP_SIM_SOURCE = " in html
    assert data["siteUrl"] == bundle.SITE_URL


def test_build_bundle_escapes_markup_inside_data(site: Path) -> None:
    (site / "index.html").write_text(page("<main><p>a</script><!-- b \u2028</p></main>"), encoding="utf-8")
    html, _ = build_bundle(site)
    raw = re.search(r'id="pp-data">(.*?)</script>', html, re.S)
    assert raw
    assert "<" not in raw.group(1)
    assert "\u2028" not in raw.group(1)
    assert "</script><!-- b \u2028" in _data(html)["pages"]["index.html"]["html"]  # type: ignore[index]


def test_build_bundle_rejects_unsafe_script(site: Path) -> None:
    (site / "assets" / "js" / "viz.js").write_text("const s = '</SCRIPT>';", encoding="utf-8")
    with pytest.raises(BundleError, match=r"viz\.js contains"):
        build_bundle(site)


def test_build_bundle_missing_asset_raises(site: Path) -> None:
    (site / "assets" / "js" / "viz-bazel.js").unlink()
    with pytest.raises(BundleError, match=r"missing asset: viz-bazel\.js"):
        build_bundle(site)


def test_build_bundle_bad_manifest_raises(site: Path) -> None:
    (site / "assets" / "js" / "curriculum.js").write_text("nothing here", encoding="utf-8")
    with pytest.raises(BundleError, match="curriculum manifest"):
        build_bundle(site)


def test_write_bundle_creates_parent_dirs(site: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "deep" / "index.html"
    count, size = write_bundle(site, out)
    assert count == 4
    assert out.stat().st_size == size


def test_build_bundle_embeds_the_simulator_safely(site: Path) -> None:
    html, _ = build_bundle(site)
    line = next(x for x in html.splitlines() if x.startswith("window.PP_SIM_SOURCE = "))
    assert "<b>" not in line
    assert json.loads(line.removeprefix("window.PP_SIM_SOURCE = ").removesuffix(";")) == '"""sim"""\nx = "<b>"\n'


def test_build_bundle_missing_simulator_raises(site: Path) -> None:
    (site / "assets" / "py" / "minibazel.py").unlink()
    with pytest.raises(BundleError, match=r"missing asset: minibazel\.py"):
        build_bundle(site)


def test_page_to_json_round_trips(site: Path) -> None:
    result = read_page(site, "modules/m01.html", "m01", "module")
    data = result.to_json()
    assert data["quizzes"] == ["m01-quiz"]
    assert json.loads(json.dumps(data))["checklists"] == {"m01-mini": 3}
