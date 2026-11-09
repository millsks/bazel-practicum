"""Shared fixtures for the practicum test suite."""

import json
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def write_manifest(
    site: Path, parts: list[dict[str, object]], reference: list[dict[str, object]] | None = None
) -> None:
    js = site / "assets" / "js"
    js.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"title": "T", "parts": parts, "reference": reference or []})
    (js / "curriculum.js").write_text(f"window.CURRICULUM = {payload};\n", encoding="utf-8")


def page(body: str, *, title: str = "Page") -> str:
    return f"<!doctype html><html><head><title>{title}</title></head><body>{textwrap.dedent(body)}</body></html>"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


CARGO_TOML = '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2024"\n\n[workspace]\n'


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A minimal practicum repository with one dependency-free Cargo project and a tiny site."""
    (tmp_path / "pixi.toml").write_text("[workspace]\nname = 'x'\n", encoding="utf-8")
    project = tmp_path / "projects" / "p01_demo"
    for crate, body in (("starter", "todo!()"), ("solution", "42")):
        (project / crate / "src").mkdir(parents=True)
        (project / crate / "Cargo.toml").write_text(CARGO_TOML, encoding="utf-8")
        (project / crate / "src" / "lib.rs").write_text(
            f"/// The answer.\npub fn answer() -> u32 {{\n    {body}\n}}\n", encoding="utf-8"
        )
    (project / "tests").mkdir()
    (project / "project.toml").write_text('id = "p01"\ntitle = "Demo"\npart = 1\npackage = "demo"\n', encoding="utf-8")
    (project / "tests" / "grade.rs").write_text(
        "#[test]\nfn answer_is_42() {\n    assert_eq!(demo::answer(), 42);\n}\n", encoding="utf-8"
    )
    site = tmp_path / "docs"
    write_manifest(site, [{"id": "part1", "modules": [{"id": "m01", "href": "modules/m01.html"}], "projects": []}])
    (site / "modules").mkdir()
    (site / "modules" / "m01.html").write_text(page("<main><h1>M01</h1></main>"), encoding="utf-8")
    return tmp_path
