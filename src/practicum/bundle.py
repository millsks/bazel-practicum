"""Build the single-file edition: one HTML page holding every module, project, and reference page of ``docs/``."""

import json
import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from practicum import __version__
from practicum.sim import simulator_path
from practicum.site import load_curriculum

SITE_URL = "https://millsks.github.io/bazel-practicum/"
REPO_URL = "https://github.com/millsks/bazel-practicum"
DESCRIPTION = "An interactive Bazel course: from Python developer to a polyglot monorepo, with a Bazel simulator in the page."
SCRIPT_ORDER = ("viz.js", "viz-bazel.js", "course.js")
ENGINE_DIR = Path(__file__).with_name("engine")

_MAIN = re.compile(r"<main\b[^>]*>(.*)</main>", re.S | re.I)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_PLACEHOLDER = re.compile(r"@@([A-Z_]+)@@")
_CSS_IMPORT = re.compile(r"^@import[^;]*;[ \t]*\n?", re.M)
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"})


class BundleError(Exception):
    """The site cannot be bundled, for example because a page or asset is missing."""


@dataclass(frozen=True, slots=True)
class Page:
    """One course page reduced to what the single-file engine needs.

    Attributes:
        id: Route id, such as ``m05``, ``p01``, ``ref-glossary``, or ``home``.
        kind: ``home``, ``module``, ``project``, or ``reference``.
        title: Text of the page's ``<title>``.
        html: Inner HTML of the page's ``<main>`` element.
        exercises: Ids of graded exercises and labs on the page.
        quizzes: Ids of quizzes on the page.
        checklists: Checklist ids mapped to their number of items.
    """

    id: str
    kind: str
    title: str
    html: str
    exercises: tuple[str, ...]
    quizzes: tuple[str, ...]
    checklists: dict[str, int]

    def to_json(self) -> dict[str, object]:
        """Return the page as a JSON-serializable mapping.

        Returns:
            The page fields, with tuples converted to lists.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "html": self.html,
            "exercises": list(self.exercises),
            "quizzes": list(self.quizzes),
            "checklists": self.checklists,
        }


class _WidgetScanner(HTMLParser):
    """Collect exercise, quiz, and checklist ids, and count each checklist's items."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.exercises: list[str] = []
        self.quizzes: list[str] = []
        self.checklists: dict[str, int] = {}
        self._depth = 0
        self._open: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())
        widget_id = attributes.get("data-id", "")
        if tag not in _VOID:
            self._depth += 1
        if tag == "li" and self._open and self._depth == self._open[-1][1] + 1:
            self.checklists[self._open[-1][0]] += 1
        if not widget_id:
            return
        if "exercise" in classes or "lab" in classes:
            self.exercises.append(widget_id)
        if "quiz" in classes:
            self.quizzes.append(widget_id)
        if "checklist" in classes:
            self.checklists[widget_id] = 0
            self._open.append((widget_id, self._depth))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if self._open and self._depth == self._open[-1][1]:
            self._open.pop()
        self._depth -= 1


def extract_main(html: str, path: str) -> str:
    """Return the inner HTML of a page's ``<main>`` element.

    Args:
        html: The full page.
        path: Page path, used in the error message.

    Returns:
        Everything between ``<main ...>`` and ``</main>``, stripped.

    Raises:
        BundleError: The page has no ``<main>`` element.
    """
    match = _MAIN.search(html)
    if match is None:
        raise BundleError(f"{path}: no <main> element")
    return match.group(1).strip()


def read_page(site_root: Path, href: str, page_id: str, kind: str) -> Page:
    """Read one page from the site and reduce it to a :class:`Page`.

    Args:
        site_root: The ``docs/`` directory.
        href: Page path relative to ``site_root``.
        page_id: Route id for the page.
        kind: Page kind.

    Returns:
        The reduced page.

    Raises:
        BundleError: The page does not exist or has no ``<main>`` element.
    """
    file = site_root / href
    if not file.is_file():
        raise BundleError(f"{href}: page does not exist")
    html = file.read_text(encoding="utf-8")
    main = extract_main(html, href)
    title = _TITLE.search(html)
    scanner = _WidgetScanner()
    scanner.feed(main)
    scanner.close()
    return Page(
        id=page_id,
        kind=kind,
        title=title.group(1).strip() if title else page_id,
        html=main,
        exercises=tuple(scanner.exercises),
        quizzes=tuple(scanner.quizzes),
        checklists=scanner.checklists,
    )


def _entries(manifest: dict[str, object]) -> list[tuple[str, str, str]]:
    entries = [("home", "index.html", "home")]
    parts = manifest.get("parts", [])
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        for key, kind in (("modules", "module"), ("projects", "project")):
            for item in part.get(key, []):
                if isinstance(item, dict):
                    entries.append((str(item["id"]), str(item["href"]), kind))
    reference = manifest.get("reference", [])
    for item in reference if isinstance(reference, list) else []:
        if isinstance(item, dict):
            entries.append((str(item["id"]), str(item["href"]), "reference"))
    return entries


def collect_pages(site_root: Path, manifest: dict[str, object]) -> dict[str, Page]:
    """Read the home page and every page listed in the curriculum manifest.

    Args:
        site_root: The ``docs/`` directory.
        manifest: The parsed curriculum manifest.

    Returns:
        Pages keyed by their path relative to ``site_root``.

    Raises:
        BundleError: Two manifest entries share an id, or a page cannot be read.
    """
    pages: dict[str, Page] = {}
    seen: set[str] = set()
    for page_id, href, kind in _entries(manifest):
        if page_id in seen:
            raise BundleError(f"duplicate id in curriculum manifest: {page_id}")
        seen.add(page_id)
        pages[href] = read_page(site_root, href, page_id, kind)
    return pages


def _asset(path: Path, closing_tag: str) -> str:
    if not path.is_file():
        raise BundleError(f"missing asset: {path.name}")
    text = path.read_text(encoding="utf-8")
    if closing_tag in text.lower():
        raise BundleError(f"{path.name} contains {closing_tag!r} and cannot be inlined")
    return text


def _json_for_script(data: object) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def fill_template(template: str, values: dict[str, str]) -> str:
    """Replace every ``@@NAME@@`` placeholder in one pass.

    Args:
        template: Text containing placeholders.
        values: Replacement text for each placeholder name.

    Returns:
        The filled template. Replacement text is never re-scanned for placeholders.

    Raises:
        BundleError: The template uses a placeholder with no value.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise BundleError(f"template placeholder has no value: {name}")
        return values[name]

    return _PLACEHOLDER.sub(replace, template)


def build_bundle(site_root: Path) -> tuple[str, int]:
    """Build the single-file edition from a ``docs/`` directory.

    Args:
        site_root: The ``docs/`` directory.

    Returns:
        The complete HTML document and the number of pages it holds.

    Raises:
        BundleError: The manifest, a page, or an asset is missing or cannot be inlined.
    """
    try:
        manifest = load_curriculum(site_root)
    except (OSError, ValueError) as exc:
        raise BundleError(f"cannot load the curriculum manifest: {exc}") from exc
    pages = collect_pages(site_root, manifest)
    js_dir = site_root / "assets" / "js"
    scripts = [_asset(js_dir / name, "</script") for name in SCRIPT_ORDER]
    scripts.append(_asset(ENGINE_DIR / "engine.js", "</script"))
    simulator = _asset(simulator_path(site_root), "</script")
    scripts.insert(0, f"window.PP_SIM_SOURCE = {_json_for_script(simulator)};")
    course_css = _CSS_IMPORT.sub("", _asset(site_root / "assets" / "css" / "course.css", "</style"))
    data = {
        "curriculum": manifest,
        "pages": {path: page.to_json() for path, page in pages.items()},
        "version": __version__,
        "siteUrl": SITE_URL,
        "repoUrl": REPO_URL,
    }
    title = str(manifest.get("title") or "Bazel Practicum")
    html = fill_template(
        (ENGINE_DIR / "template.html").read_text(encoding="utf-8"),
        {
            "TITLE": escape(title),
            "DESCRIPTION": escape(DESCRIPTION),
            "COURSE_CSS": course_css,
            "ENGINE_CSS": _asset(ENGINE_DIR / "engine.css", "</style"),
            "DATA": _json_for_script(data),
            "SCRIPTS": "\n".join(f"<script>\n{source}\n</script>" for source in scripts),
        },
    )
    return html, len(pages)


def write_bundle(site_root: Path, out: Path) -> tuple[int, int]:
    """Build the single-file edition and write it to disk.

    Args:
        site_root: The ``docs/`` directory.
        out: Destination file; parent directories are created.

    Returns:
        The number of pages bundled and the size of the file in bytes.
    """
    html, count = build_bundle(site_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = html.encode("utf-8")
    out.write_bytes(data)
    return count, len(data)
