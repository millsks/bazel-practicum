"""Whole-repository quality gates: the site is valid, every exercise checks out, and the bundle builds."""

import json
import re
from pathlib import Path

import pytest

from practicum.bundle import write_bundle
from practicum.exercises import check_page
from practicum.site import check_site, load_curriculum
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.integration

SITE = REPO_ROOT / "docs"
PAGES = sorted(SITE.rglob("*.html"))


def test_site_has_no_issues() -> None:
    issues = check_site(SITE)
    assert not issues, "\n".join(f"{i.path}: {i.message}" for i in issues)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(SITE).as_posix())
def test_exercises_and_sandboxes_check_out(page: Path) -> None:
    failures = [r for r in check_page(SITE, page) if not r.ok]
    assert not failures, "\n".join(f"{r.id}: {r.detail}" for r in failures)


def test_bundle_holds_every_manifest_page(tmp_path: Path) -> None:
    out = tmp_path / "index.html"
    count, size = write_bundle(SITE, out)
    assert size < 16 * 1024 * 1024
    match = re.search(r'<script type="application/json" id="pp-data">(.*?)</script>', out.read_text("utf-8"), re.S)
    assert match
    data = json.loads(match.group(1))
    manifest = load_curriculum(SITE)
    expected = {"home"} | {str(r["id"]) for r in manifest["reference"]}  # type: ignore[attr-defined]
    for part in manifest["parts"]:  # type: ignore[attr-defined]
        expected |= {str(m["id"]) for m in part["modules"] + part["projects"]}
    assert {p["id"] for p in data["pages"].values()} == expected
    assert count == len(expected)
