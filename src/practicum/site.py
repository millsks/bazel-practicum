"""Static validation for the curriculum website under ``docs/``."""

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

QUESTION_TYPES = frozenset({"single", "multi", "output", "text"})
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "javascript:", "data:", "//")
_VIZ_REGISTRATION = re.compile(r"""registerViz\(\s*["']([\w-]+)["']""")


@dataclass(frozen=True, slots=True)
class Issue:
    """A single problem found in the site.

    Attributes:
        path: File the problem was found in, relative to the site root.
        message: Description of the problem.
    """

    path: str
    message: str


@dataclass
class _PageScan:
    links: list[str] = field(default_factory=list)
    ids: set[str] = field(default_factory=set)
    quizzes: list[tuple[str, str]] = field(default_factory=list)
    exercises: list[tuple[str, bool]] = field(default_factory=list)
    labs: list[str] = field(default_factory=list)
    viz: list[str] = field(default_factory=list)
    module_id: str | None = None
    title: str = ""


class _PageParser(HTMLParser):
    """Collect links, ids, quiz payloads, exercises, and visualizers from one page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scan = _PageScan()
        self._quiz_stack: list[str] = []
        self._exercise_stack: list[list[object]] = []
        self._depth = 0
        self._quiz_depths: list[int] = []
        self._exercise_depths: list[int] = []
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())
        void = tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
        if not void:
            self._depth += 1
        self.scan.links.extend(attributes[name] for name in ("href", "src") if name in attributes)
        if "id" in attributes:
            self.scan.ids.add(attributes["id"])
        if tag == "body" and "data-module" in attributes:
            self.scan.module_id = attributes["data-module"]
        if "data-viz" in attributes:
            self.scan.viz.append(attributes["data-viz"])
        if "quiz" in classes:
            self._quiz_stack.append(attributes.get("data-id", ""))
            self._quiz_depths.append(self._depth)
        if "exercise" in classes:
            self._exercise_stack.append([attributes.get("data-id", ""), False])
            self._exercise_depths.append(self._depth)
        if "lab" in classes and tag == "div":
            self.scan.labs.append(attributes.get("data-id", ""))
        if tag == "script":
            script_type = attributes.get("type", "")
            if script_type == "application/json" and self._quiz_stack:
                self._capture = "quiz"
                self._buffer = []
            elif "tests" in classes and self._exercise_stack:
                self._exercise_stack[-1][1] = True
        if tag == "title":
            self._capture = "title"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "quiz" and tag == "script":
            self.scan.quizzes.append((self._quiz_stack[-1], "".join(self._buffer)))
            self._capture = None
        elif self._capture == "title" and tag == "title":
            self.scan.title = "".join(self._buffer).strip()
            self._capture = None
        if self._quiz_depths and self._quiz_depths[-1] == self._depth:
            self._quiz_depths.pop()
            self._quiz_stack.pop()
        if self._exercise_depths and self._exercise_depths[-1] == self._depth:
            self._exercise_depths.pop()
            exercise_id, has_tests = self._exercise_stack.pop()
            self.scan.exercises.append((str(exercise_id), bool(has_tests)))
        self._depth -= 1


def scan_page(html: str) -> _PageScan:
    """Parse one HTML page and collect the facts the checks need.

    Args:
        html: Page source.

    Returns:
        The collected scan results.
    """
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    return parser.scan


def validate_quiz(payload: str) -> list[str]:
    """Validate a quiz JSON payload.

    Args:
        payload: Raw JSON text from a quiz's ``<script type="application/json">`` block.

    Returns:
        Human-readable problems; empty when the quiz is valid.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or not questions:
        return ["quiz needs a non-empty 'questions' list"]
    problems: list[str] = []
    for number, question in enumerate(questions, start=1):
        problems.extend(f"question {number}: {p}" for p in _validate_question(question))
    return problems


def _validate_question(question: object) -> list[str]:
    if not isinstance(question, dict):
        return ["must be an object"]
    kind = question.get("type", "single")
    if kind not in QUESTION_TYPES:
        return [f"unknown type {kind!r}"]
    problems = [f"missing {key!r}" for key in ("prompt", "explanation") if not question.get(key)]
    answer = question.get("answer")
    if kind in {"single", "multi"}:
        options = question.get("options")
        if not isinstance(options, list) or len(options) < 2:
            return [*problems, "needs at least two 'options'"]
        indexes = answer if kind == "multi" else [answer]
        if not isinstance(indexes, list) or not indexes:
            problems.append("multi 'answer' must be a non-empty list of option indexes")
        elif not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(options) for i in indexes):
            problems.append("'answer' must reference valid option indexes")
    elif not isinstance(answer, str) and not (
        isinstance(answer, list) and answer and all(isinstance(a, str) for a in answer)
    ):
        problems.append("'answer' must be a string or list of accepted strings")
    return problems


def _broken_link(page: Path, site_root: Path, link: str, ids: set[str]) -> str | None:
    if not link or link.startswith(_EXTERNAL_PREFIXES):
        return None
    parts = urlsplit(link)
    if not parts.path:
        fragment = unquote(parts.fragment)
        return None if not fragment or fragment in ids else f"missing anchor #{fragment}"
    target = (page.parent / unquote(parts.path)).resolve()
    if not target.is_relative_to(site_root.resolve()):
        return f"link escapes the site: {link}"
    if target.is_dir():
        target = target / "index.html"
    return None if target.exists() else f"broken link: {link}"


def load_curriculum(site_root: Path) -> dict[str, object]:
    """Load the curriculum manifest embedded in ``assets/js/curriculum.js``.

    Args:
        site_root: The ``docs/`` directory.

    Returns:
        The manifest as a dictionary.

    Raises:
        ValueError: If the manifest is missing or not valid JSON.
    """
    source = (site_root / "assets" / "js" / "curriculum.js").read_text(encoding="utf-8")
    start, end = source.find("{"), source.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("curriculum.js does not contain a JSON object")
    try:
        manifest: dict[str, object] = json.loads(source[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"curriculum.js is not valid JSON: {exc}") from exc
    return manifest


def registered_visualizers(site_root: Path) -> set[str]:
    """Return the visualizer names registered in ``assets/js/viz*.js``.

    Args:
        site_root: The ``docs/`` directory.

    Returns:
        Registered visualizer names.
    """
    names: set[str] = set()
    for script in (site_root / "assets" / "js").glob("viz*.js"):
        names.update(_VIZ_REGISTRATION.findall(script.read_text(encoding="utf-8")))
    return names


def _manifest_pages(manifest: dict[str, object]) -> list[str]:
    pages: list[str] = []
    parts = manifest.get("parts", [])
    for part in parts if isinstance(parts, list) else []:
        for key in ("modules", "projects"):
            for entry in part.get(key, []) if isinstance(part, dict) else []:
                if isinstance(entry, dict) and isinstance(entry.get("href"), str):
                    pages.append(entry["href"])
    extras = manifest.get("reference", [])
    for entry in extras if isinstance(extras, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("href"), str):
            pages.append(entry["href"])
    return pages


def check_site(site_root: Path) -> list[Issue]:
    """Validate every page under ``site_root``.

    Checks local links and anchors, quiz payloads, exercise test blocks, visualizer names,
    page titles, and that every page in the curriculum manifest exists.

    Args:
        site_root: The ``docs/`` directory.

    Returns:
        Every problem found; empty when the site is valid.
    """
    issues: list[Issue] = []
    labs_root = site_root.parent / "labs"
    known_labs = {p.parent.name for p in labs_root.glob("*/lab.toml")}
    referenced_labs: set[str] = set()
    try:
        manifest = load_curriculum(site_root)
    except (OSError, ValueError) as exc:
        return [Issue("assets/js/curriculum.js", str(exc))]
    for href in _manifest_pages(manifest):
        if not (site_root / href).is_file():
            issues.append(Issue("assets/js/curriculum.js", f"manifest page does not exist: {href}"))
    known_viz = registered_visualizers(site_root)
    seen_exercises: dict[str, str] = {}
    for page in sorted(site_root.rglob("*.html")):
        relative = page.relative_to(site_root).as_posix()
        scan = scan_page(page.read_text(encoding="utf-8"))
        if not scan.title:
            issues.append(Issue(relative, "page has no <title>"))
        for link in scan.links:
            problem = _broken_link(page, site_root, link, scan.ids)
            if problem:
                issues.append(Issue(relative, problem))
        for quiz_id, payload in scan.quizzes:
            label = quiz_id or "(no data-id)"
            issues.extend(Issue(relative, f"quiz {label}: {p}") for p in validate_quiz(payload))
        for exercise_id, has_tests in scan.exercises:
            if not exercise_id:
                issues.append(Issue(relative, "exercise without data-id"))
            elif exercise_id in seen_exercises:
                issues.append(Issue(relative, f"exercise id {exercise_id} also used in {seen_exercises[exercise_id]}"))
            else:
                seen_exercises[exercise_id] = relative
            if not has_tests:
                issues.append(Issue(relative, f"exercise {exercise_id or '(no data-id)'} has no tests script"))
        issues.extend(Issue(relative, f"unknown visualizer {name!r}") for name in scan.viz if name not in known_viz)
        for lab_id in scan.labs:
            if not lab_id:
                issues.append(Issue(relative, "lab without data-id"))
            elif lab_id not in known_labs:
                issues.append(Issue(relative, f"lab {lab_id} has no labs/{lab_id}/lab.toml"))
            referenced_labs.add(lab_id)
    issues.extend(
        Issue(f"../labs/{lab_id}", "lab is not introduced by any page") for lab_id in sorted(known_labs - referenced_labs)
    )
    return issues
