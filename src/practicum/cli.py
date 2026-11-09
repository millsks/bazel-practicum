"""Command-line interface: ``practicum labs|start|grade|serve|check-site|check-exercises|check-labs|bundle``."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from practicum import __version__
from practicum.bundle import BundleError, write_bundle
from practicum.exercises import check_page
from practicum.labs import (
    CheckResult,
    LabError,
    Source,
    discover_labs,
    get_lab,
    grade_lab,
    resolve_source,
    start_lab,
)
from practicum.log import configure_logging, get_logger
from practicum.serve import serve
from practicum.site import check_site
from practicum.workspace import WorkspaceNotFoundError, find_root


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every subcommand.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(prog="practicum", description="Bazel Practicum learner tools.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--json", action="store_true", help="emit JSON log lines")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("labs", help="list every lab and whether you have started it")

    start = commands.add_parser("start", help="copy a lab's starter workspace into work/")
    start.add_argument("lab", help="lab id, e.g. m01-lab1 or c1")
    start.add_argument("--force", action="store_true", help="overwrite an existing working copy")

    grade = commands.add_parser("grade", help="run a lab's checks against your workspace with real Bazel")
    grade.add_argument("lab", help="lab id, e.g. m01-lab1 or c1")
    grade.add_argument("--source", choices=[s.value for s in Source], help="which copy of the workspace to grade")

    serve_cmd = commands.add_parser("serve", help="serve the course website locally")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8000)
    serve_cmd.add_argument("--no-browser", action="store_true", help="do not open a browser window")

    commands.add_parser("check-site", help="validate links, quizzes, exercises, and labs referenced by docs/")

    exercises = commands.add_parser(
        "check-exercises", help="run each exercise's solution and starter, and each sandbox, through the simulator"
    )
    exercises.add_argument("pages", nargs="*", type=Path, help="HTML pages to check (default: every page in docs/)")

    check_labs = commands.add_parser(
        "check-labs", help="grade every lab's solution (must pass) and starter (must fail) with real Bazel"
    )
    check_labs.add_argument("labs", nargs="*", help="lab ids (default: all)")
    check_labs.add_argument("--solutions-only", action="store_true", help="skip grading the starters")

    bundle = commands.add_parser("bundle", help="build the single-file edition of the course website")
    bundle.add_argument(
        "--out",
        type=Path,
        default=Path("dist/bazel-practicum.html"),
        help="output file, relative to the repository root",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments excluding the program name; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    configure_logging(json=args.json)
    log = get_logger()
    try:
        root = find_root()
        return _dispatch(args, root)
    except (WorkspaceNotFoundError, LabError) as exc:
        log.error("command_failed", command=args.command, reason=str(exc))
        return 2


def _dispatch(args: argparse.Namespace, root: Path) -> int:
    log = get_logger()
    site_root = root / "docs"
    if args.command == "labs":
        for lab in discover_labs(root):
            log.info("lab", id=lab.id, module=lab.module, title=lab.title, started=lab.work_dir(root).is_dir())
        return 0
    if args.command == "start":
        lab = get_lab(root, args.lab)
        destination = start_lab(root, lab, force=args.force)
        log.info("lab_started", id=lab.id, work_dir=str(destination.relative_to(root)))
        return 0
    if args.command == "grade":
        return _grade(root, args.lab, Source(args.source) if args.source else None)
    if args.command == "serve":
        log.info("serving", url=f"http://{args.host}:{args.port}/", root=str(site_root))
        try:
            serve(site_root, args.host, args.port, open_browser=not args.no_browser)
        except KeyboardInterrupt:
            log.info("server_stopped")
        return 0
    if args.command == "bundle":
        return _bundle(site_root, root / args.out)
    if args.command == "check-exercises":
        return _check_exercises(site_root, args.pages or sorted(site_root.rglob("*.html")))
    if args.command == "check-labs":
        return _check_labs(root, args.labs, solutions_only=args.solutions_only)
    issues = check_site(site_root)
    for issue in issues:
        log.error("site_issue", path=issue.path, message=issue.message)
    log.info("site_checked", issues=len(issues))
    return 1 if issues else 0


def _print_result(result: CheckResult) -> None:
    mark = "✓" if result.ok else "✗"
    print(f"  {mark} {result.name}" + (f"\n      {result.detail}" if result.detail else ""), flush=True)


def _grade(root: Path, lab_id: str, source: Source | None) -> int:
    log = get_logger()
    lab = get_lab(root, lab_id)
    chosen, code_dir = resolve_source(root, lab, source)
    if chosen is Source.STARTER and source is None:
        log.warning("grading_starter", hint=f"you have not started this lab; run `pixi run start {lab.id}` first")
    log.info("grading", id=lab.id, source=chosen.value, workspace=str(code_dir.relative_to(root)))
    print(f"{lab.title}", flush=True)
    results = grade_lab(root, lab, source=chosen, on_result=_print_result)
    passed = sum(r.ok for r in results)
    print(
        f"\n{passed}/{len(results)} checks passed." + (" Lab complete." if passed == len(results) else ""), flush=True
    )
    return 0 if passed == len(results) else 1


def _bundle(site_root: Path, out: Path) -> int:
    log = get_logger()
    try:
        pages, size = write_bundle(site_root, out)
    except BundleError as exc:
        log.error("bundle_failed", reason=str(exc))
        return 1
    log.info("bundled", pages=pages, bytes=size, out=str(out))
    return 0


def _check_exercises(site_root: Path, pages: list[Path]) -> int:
    log = get_logger()
    failed = 0
    total = 0
    for page in pages:
        for result in check_page(site_root, page):
            total += 1
            if not result.ok:
                failed += 1
                log.error("exercise_failed", page=str(page), id=result.id, detail=result.detail)
    log.info("exercises_checked", total=total, failed=failed)
    return 1 if failed else 0


def _check_labs(root: Path, wanted: list[str], *, solutions_only: bool) -> int:
    log = get_logger()
    labs = [get_lab(root, w) for w in wanted] if wanted else discover_labs(root)
    failed: list[str] = []
    for lab in labs:
        solution = grade_lab(root, lab, source=Source.SOLUTION)
        bad = [r for r in solution if not r.ok]
        for r in bad:
            log.error("solution_check_failed", id=lab.id, check=r.name, detail=r.detail)
        if bad:
            failed.append(lab.id)
            continue
        if not solutions_only:
            starter = grade_lab(root, lab, source=Source.STARTER)
            if all(r.ok for r in starter):
                log.error("starter_passes", id=lab.id, hint="the starter already passes every check")
                failed.append(lab.id)
                continue
        log.info("lab_ok", id=lab.id, checks=len(solution))
    log.info("labs_checked", total=len(labs), failed=len(failed))
    return 1 if failed else 0
