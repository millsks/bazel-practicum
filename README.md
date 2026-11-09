# bazel-practicum

An interactive course that takes a Python developer from no Bazel to growing a polyglot (Python and Go) monorepo
with Bazel 9. Every idea starts from what you already do with pip, pyproject.toml, and pytest, and lands in a real
workspace. Everything, including Bazel itself (through Bazelisk), is managed with Pixi.

[![CI](https://github.com/millsks/bazel-practicum/actions/workflows/ci.yml/badge.svg)](https://github.com/millsks/bazel-practicum/actions/workflows/ci.yml)
![coverage](https://img.shields.io/badge/coverage-%E2%89%A590%25-brightgreen)
![bazel](https://img.shields.io/badge/bazel-9.3.2-43a047)
![pixi](https://img.shields.io/badge/managed%20by-pixi-orange)

## What's inside

- **Level 1 (Building with Bazel):** an orientation module and ten modules in two stages, *Foundations*
  (workspaces and targets, the build graph and caching, rules_python, Bzlmod and PyPI) and *Growing the Monorepo*
  (testing at scale, configuration and `select()`, Go with rules_go, generated files and macros, query and
  debugging), plus the capstone **c1**, a polyglot monorepo graded by real Bazel. Published as static HTML in
  [`docs/`](docs/).
- **Levels 2-3** (toolchains, remote caching and execution, CI, containers, Gazelle; then Starlark rules,
  providers, and aspects) are on the [roadmap](docs/reference/roadmap.html).
- **A Bazel simulator in the page.** Sandboxes and graded exercises run *minibazel*
  ([`docs/assets/py/minibazel.py`](docs/assets/py/minibazel.py)) in your browser on Pyodide. It models Bazel's
  loading and analysis phases (labels, visibility, providers, `select()`, `.bazelrc`, `bazel query` and `cquery`,
  test selection) with Bazel 9.3's error messages. It never runs anything.
- **Labs with real Bazel.** Anything that needs execution (tests passing, cache hits, generated files) is a lab in
  [`labs/`](labs/): a starter workspace, a reference solution, and checks that run real Bazel commands against your
  copy.

## Installation

Install [Pixi](https://pixi.sh), then:

```sh
git clone https://github.com/millsks/bazel-practicum.git
cd bazel-practicum
pixi install            # Python tooling and Bazelisk from conda-forge
pixi run bazel version  # Bazelisk downloads Bazel 9.3.2 on first use
pixi run bootstrap      # pre-commit hooks (only needed if you contribute)
```

No Homebrew, system Python, or Java needed: Bazel ships its own JDK, and every lab pins Bazel in `.bazelversion`.

## Quick start

```sh
pixi run serve          # opens the course at http://127.0.0.1:8000/
```

Start with **Module 00: How This Practicum Works**. Each module ends with labs:

```sh
pixi run labs               # list labs and whether you've started them
pixi run start m00-lab1     # copy the starter workspace into work/m00-lab1/
cd work/m00-lab1
pixi run bazel build //...  # work on it with real Bazel
cd ../..
pixi run grade m00-lab1     # run the lab's checks against work/m00-lab1 with real Bazel
```

Grading copies your workspace (plus any grading files) to `build/labs/`, so your copy in `work/` is never modified.

## Development

```sh
pixi run test               # unit tests (fast), including the simulator suite
pixi run cov                # unit tests with a coverage gate (>= 90% of src/)
pixi run test-integration   # site, exercises, bundle, and a differential test of the simulator against real Bazel
pixi run check-site         # links, anchors, quizzes, exercise blocks, lab ids, and visualizers in docs/
pixi run check-exercises    # every exercise's solution passes and starter fails in the simulator; sandboxes run
pixi run check-labs         # every lab's solution passes and starter fails with real Bazel
pixi run bundle             # build the single-file edition: dist/bazel-practicum.html
pixi run ci                 # pre-commit, build, mypy, ruff, site and exercise checks, and tests with coverage
```

Lesson authors should read [`docs/AUTHORING.md`](docs/AUTHORING.md); the live component gallery is
[`docs/authoring/components.html`](docs/authoring/components.html).

## License

[MIT](LICENSE)
