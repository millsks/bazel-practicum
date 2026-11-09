# Authoring Guide

How lesson, project, and reference pages in `docs/` and labs in `labs/` are built. The live gallery of every
component is `docs/authoring/components.html` (`pixi run serve`, then open `/authoring/components.html`).

A page is done when all of these pass:

- `pixi run check-site`: links, anchors, quizzes, exercise blocks, lab ids, visualizer names.
- `pixi run check-exercises docs/modules/<page>.html`: every exercise's reference solution passes its checks in
  the simulator, every starter fails at least one, and every sandbox command runs.
- `pixi run check-labs <lab-id> ...`: every lab's solution passes its checks with **real Bazel** and its starter
  fails at least one.

## Who the course is for

A working Python developer who uses Pixi and pytest daily and has never used Bazel. They know packages, imports,
virtual environments, `pip`, `pyproject.toml`, and tests. They do not know Starlark, build graphs, or any other
build system beyond `pip install -e .`. Level 1 ("Building with Bazel") ends when they can grow a small polyglot
monorepo (Python and Go) with Bazel 9: write BUILD files from a blank page, add PyPI and BCR dependencies, keep
tests fast and cached, configure builds with flags and `select()`, generate files, and answer "what depends on
this?" with `bazel query`.

Teach every idea in three steps:

1. **From Python.** Start from what the learner already does ("You run `pytest tests/` and it finds tests by
   name...").
2. **The Bazel idea.** Explain what Bazel does and *why* (the guarantee it buys: correctness, caching, scale),
   with a sandbox the learner can run.
3. **For real.** Show it in a real workspace: a lab graded by real Bazel, or exact real output (copied from a
   run, not invented) in a `pre` block.

## The two engines: simulator and real Bazel

**The simulator** (`docs/assets/py/minibazel.py`, run in the browser on Pyodide) evaluates MODULE.bazel, BUILD and
.bzl files, and models Bazel's **loading and analysis** phases: labels, packages, target patterns, visibility,
providers (`PyInfo`, `GoInfo`), `testonly`, cycles, `select()` with `config_setting`/flags/platforms, `.bazelrc`
and `--config`, `bazel query` (deps, rdeps, allrdeps, somepath, allpaths, kind, attr, filter, labels, tests,
set, siblings, buildfiles, `+ - ^`), `bazel cquery`, and which tests `bazel test` selects (tags, sizes,
`manual`, `test_suite`). Its error messages copy Bazel 9.3's wording. It **does not run anything**: no
compiling, no Python execution, no genrule commands, no test results, no `aquery`, no remote cache.

Sandboxes and exercises use the simulator; labs use real Bazel. When a lesson shows something the simulator
cannot (a test passing, cache hits, `aquery`, a genrule's output), show real output and make it a lab, and say so
with a `callout sim`.

Rules the simulator knows (anything else is a loading error, as in real Bazel): native `filegroup`, `genrule`,
`test_suite`, `config_setting`, `alias`, `package_group`, `platform`, `constraint_setting`, `constraint_value`,
`exports_files`, `package`, `glob`, `select`; `@rules_python//python:defs.bzl` (`py_library`, `py_binary`,
`py_test`), `@rules_python//python:pip.bzl` (`compile_pip_requirements`), `@rules_go//go:def.bzl`
(`go_library`, `go_binary`, `go_test`), `@rules_shell//shell:sh_{binary,test,library}.bzl`,
`@bazel_skylib//rules:{write_file,copy_file,diff_test,run_binary,build_test,common_settings}.bzl`. MODULE.bazel:
`module`, `bazel_dep`, `use_extension`/`use_repo` (pip `parse`, python `toolchain`, go_sdk `download`), and the
override functions. `@pypi//<name>` exists only if `<name>` is pinned in the hub's lock file.

If you find the simulator disagreeing with real Bazel 9.3.2, fix the simulator (and add a unit test in
`tests/unit/test_minibazel.py`) rather than writing around it.

## Bazel facts to teach (and never contradict)

Verified against real runs of Bazel 9.3.2 (November 2026). Re-verify anything else in a real workspace before you
write it down.

- **Versions.** Bazel **9.3.2** (9.x is the current LTS, released January 2026; 8.x is security-only). Every
  workspace pins it in `.bazelversion`; Bazelisk (`bazelisk` 1.29 from conda-forge, wrapped as `bazel` by this
  repository's `bin/bazel`) downloads and runs that version. Module versions used throughout:
  `rules_python` **2.4.6**, `rules_go` **0.65.0**, `rules_shell` **0.8.0**, `bazel_skylib` **1.9.2**,
  `platforms` **1.1.0**. Go SDK **1.25.3** via `go_sdk.download`. Python toolchain **3.13** via
  `python.toolchain(python_version = "3.13", is_default = True)`.
- **WORKSPACE is gone.** Bazel 8 disabled it by default; Bazel 9 removed it. External dependencies are declared in
  `MODULE.bazel` (Bzlmod). Do not teach WORKSPACE except to say it existed and how to recognize old tutorials.
- **No autoloads in Bazel 9.** Rules from rule sets must be `load()`ed: `py_binary`, `sh_test`, `go_library`, all of
  them. Without the load, loading fails with `name 'py_binary' is not defined`. Native, always-available
  functions: `filegroup`, `genrule`, `test_suite`, `config_setting`, `alias`, `exports_files`, `package`, `glob`,
  `select`, `package_group`, `platform`, `constraint_*`.
- **Starlark in BUILD files** has no `def`, no `lambda`, and no top-level `for`/`if` statements (comprehensions and
  `x if c else y` are fine). Starlark has no f-strings, `while`, `try`, `import`, `is`, `**`, sets, or chained
  comparisons; use `"%s" % x` or `"{}".format(x)`.
- **Visibility.** Targets are private to their package by default (`//visibility:private`). Source files in
  another package are also not visible unless that package `exports_files()` them (Bazel 9 reports this as a
  visibility error). `package(default_visibility = [...])` changes the default for a package.
- **Labels.** `@repo//pkg/path:name`; `//pkg` means `//pkg:pkg`; `:name` and `name` are relative to the current
  package. A label cannot reach into a subpackage: `//a:b/c.txt` is invalid when `a/b` has a BUILD file.
- **Target patterns.** `//...` is every rule target in the main repository (not files); `//pkg:all` the rules in
  one package; `//pkg:*` (or `:all-targets`) rules and files. Wildcards skip targets tagged `manual`; a
  `test_suite` that names a manual test still runs it.
- **Missing source files** are not loading or analysis errors when the label is in the same package: the build
  fails at execution with `missing input file '//pkg:x.py'`.
- **py_binary's main.** Without `main`, `py_binary(name = "app")` requires `app.py` in `srcs` (error: "corresponding
  default 'app.py' does not appear in srcs").
- **query vs cquery.** `bazel query` runs before configuration, so it reports **both** branches of every `select()`
  and includes implicit and toolchain dependencies (`--noimplicit_deps` hides most). `bazel cquery` resolves
  `select()` for the flags you pass. Default `query` output is sorted labels.
- **Caching.** An action's key is a hash of its command, environment, and input contents. Tests are actions: an
  unchanged test reports `(cached) PASSED`. `bazel clean` is almost never needed; `--disk_cache=PATH` gives a
  shared local cache.
- **PyPI hubs.** rules_python 2.4.6 reserves `hub_name = "pypi"` (every build warns). Name the hub after the
  module and alias it: `pip.parse(hub_name = "weather_pypi", ...)` then `use_repo(pip, pypi = "weather_pypi")`, so
  labels stay `@pypi//requests`. Labels use the normalized distribution name (lowercase, `-` and `.` to `_`).
  A `py_test` that uses pytest needs a main shim (`main = "pytest_main.py"` calling `pytest.main(sys.argv[1:])`),
  or it passes without running anything. Tag `compile_pip_requirements` targets `manual` (their test needs the network).
- **MODULE.bazel.lock** is generated; commit it in real projects (this repository ignores it inside lab copies).
- Bazel convenience symlinks: `bazel-bin`, `bazel-out`, `bazel-testlogs`, `bazel-<workspace name>`.

## Pixi conventions

Pixi installs everything, including Bazelisk. Never tell the learner to use Homebrew, `npm install -g`,
`curl | sh`, `pip`, or a system Bazel. In this repository, `pixi run bazel ...` works from any subdirectory
(`pixi shell` puts `bazel` on PATH). For a fresh workspace outside this repository:

```sh
pixi init my-repo && cd my-repo
pixi add bazelisk
echo "9.3.2" > .bazelversion
pixi run bazelisk build //...
```

## Page skeleton

Module pages live at `docs/modules/<id>-<slug>.html` with the exact `href` from `docs/assets/js/curriculum.js`.
Project pages live at `docs/projects/`, reference pages at `docs/reference/`. All use `data-root="../"`.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>M03 · Python with rules_python · Bazel Practicum</title>
<link rel="stylesheet" href="../assets/css/course.css">
<script src="../assets/js/curriculum.js"></script>
<script src="../assets/js/viz.js" defer></script>
<script src="../assets/js/viz-bazel.js" defer></script>
<script src="../assets/js/course.js" defer></script>
</head>
<body data-root="../" data-module="m03">
<main class="lesson">
  <header class="lesson-hero">
    <p class="eyebrow">Stage 1 · Foundations · Module 03</p>
    <h1>Python with rules_python</h1>
    <p class="lede">One or two sentences on why this matters.</p>
    <div class="lesson-meta"><span>⏱ ~2.5 hours</span><span>Prerequisites: <a href="m02-build-graph.html">M02</a></span></div>
    <ul class="objectives"><li>…</li></ul>
  </header>
  <section class="lesson-section" id="some-topic"><h2>Some topic</h2> … </section>
  …
</main>
</body>
</html>
```

`course.js` adds the header, sidebar, table of contents (from each `section.lesson-section[id] > h2`), the
"Mark complete" box, notes, and previous/next links. Do not write those yourself. Reference pages use
`data-page="ref-glossary"` (the manifest id) instead of `data-module`; the capstone uses `data-module="c1"`.

## Required module structure

1. Hero: eyebrow, `h1`, lede, meta (time and prerequisites), objectives (4–7 items).
2. Six to ten teaching sections. Each explains the idea in plain language, shows a worked example, and makes the
   learner do something: a sandbox, a `data-predict` sandbox, a visualizer, or a `callout think`.
3. `id="practice"`: **three to five graded exercises**, easy to hard.
4. `id="lab"`: **one or two labs** (real Bazel, in `labs/`), introduced with what they prove that the simulator
   cannot.
5. `id="quiz"`: an end-of-module quiz of 10–15 questions mixing `single`, `multi`, `output`, and `text`.
6. `id="recap"`: a summary list, flashcards (8–12 cards), and "Going further" links to bazel.build docs, the
   rule set's docs (rules-python.readthedocs.io, github.com/bazel-contrib/rules_go), and the Bazel Central
   Registry (registry.bazel.build).

Write for a motivated developer: define every term on first use, explain *why* as well as *how*, show the mistakes
Python developers actually make (and the exact error each one produces), and finish each section with what to
remember. Aim for the depth of a good textbook chapter: a module page is typically 700–1100 lines of HTML. Keep
sentences short and paragraphs to three or four sentences; many readers are on a phone.

## Components

### Static code

```html
<pre data-label="app/BUILD.bazel"><code class="language-starlark">py_binary(name = "hello", srcs = ["hello.py"])</code></pre>
<pre data-label="Terminal"><code class="language-bash">pixi run bazel build //app:hello</code></pre>
<pre data-label="Real output (Bazel 9.3.2)"><code class="language-none">INFO: Build completed successfully, 12 total actions</code></pre>
```

Languages: starlark (BUILD, .bzl, MODULE.bazel), python, go, bash, toml, yaml, json, ini, diff, none. Escape `<`,
`>`, and `&` inside `<pre>`.

### Sandboxes (the simulator in the page)

```html
<div class="runnable" data-title="Your first BUILD file" data-commands="bazel query //...|bazel build //app:hello">
<textarea class="file" data-path="MODULE.bazel" data-readonly>
module(name = "hello")
bazel_dep(name = "rules_python", version = "2.4.6")
</textarea>
<textarea class="file" data-path="app/BUILD.bazel">
load("@rules_python//python:defs.bzl", "py_binary")

py_binary(name = "hello", srcs = ["hello.py"])
</textarea>
<textarea class="file" data-path="app/hello.py" data-hidden>print("hi")</textarea>
</div>
```

- Each `textarea.file` is one workspace file. `data-readonly` shows it locked; `data-hidden` keeps it out of the
  tabs but in the workspace (listed under "Also in the workspace"). Source files that only need to exist can be
  hidden and empty.
- Text inside `textarea` is literal except entities: write `&lt;` for `<` and `&amp;` for `&`. Never write
  `</textarea>` inside one. Content is dedented.
- `data-commands` holds one or more commands separated by `|` (the first fills the command box; all become
  buttons). Commands: `bazel build|test|run|query|cquery|version ...`, with flags such as `-c opt`,
  `--config=ci`, `--//pkg:flag=value`, `--platforms=//:p`, `--test_tag_filters=-slow`,
  `--output=label_kind`. Quote query expressions: `bazel query 'deps(//app:hello)'`.
- `data-predict`: the learner types a prediction of the output first.
- The simulator prints Bazel's errors and `(simulated)` summaries. It is honest about not running things.

### Exercises (graded by the simulator)

```html
<div class="exercise" data-id="m03-e1" data-title="Split a library out of a binary">
  <div class="exercise-prompt"><p>Task, acceptance criteria, and any constraints…</p></div>
<textarea class="file" data-path="MODULE.bazel" data-readonly>…</textarea>
<textarea class="file" data-path="app/BUILD.bazel">starter…</textarea>
<textarea class="file" data-path="app/hello.py" data-hidden></textarea>
<script type="text/x-python" class="tests">
def test_greet_is_a_library(bazel):
    t = bazel.target("//lib:greet")
    assert t.kind == "py_library", f"//lib:greet should be a py_library, but it is a {t.kind}"

def test_hello_depends_on_greet(bazel):
    deps = bazel.query("deps(//app:hello, 1)")
    assert "//lib:greet" in deps, "//app:hello must list //lib:greet in deps"

def test_everything_analyzes(bazel):
    result = bazel.build("//...")
    assert result.ok, "bazel build //... fails:\n" + result.error
</script>
<details class="hint"><summary>Hint</summary><p>…</p></details>
<details class="solution"><summary>Show solution</summary>
<pre data-path="lib/BUILD.bazel"><code class="language-starlark">…</code></pre>
<pre data-path="app/BUILD.bazel"><code class="language-starlark">…</code></pre>
</details>
</div>
```

- `data-id` is unique across the site: `<module id>-e<n>`.
- Checks are Python functions named `test_*` that take `bazel`, a fresh simulator over the learner's files. The
  name (underscores to spaces) is the check's label. Write a learner-facing message on **every** assert. A
  `BazelError` raised by a check is shown as "Bazel reported an error: …", so `bazel.target()` on a missing
  target is a fine check by itself.
- The solution is every `pre[data-path] > code` inside `details.solution`; each replaces the file at that path
  (the path must exist in the starter; add an empty editable `textarea.file` if the learner must create a file).
  `pixi run check-exercises` requires the solution to pass and the starter to fail at least one check.
- The simulator API for checks:

| Call | Returns |
|---|---|
| `bazel.target("//pkg:name")` | `Target` with `.kind` (`"py_binary"`, `"source file"`, `"generated file"`), `.attrs` (dict as written), `.tags`, `.label`; raises `BazelError` if it does not exist or its package fails to load |
| `bazel.exists(label)` | `bool` |
| `bazel.attr(label, name, *flags)` | an attribute as written, or select()-resolved for the flags |
| `bazel.query(expr)` | sorted label strings, like `bazel query`; raises `BazelError` |
| `bazel.cquery(expr, *flags)` | like query with `select()` resolved |
| `bazel.build(*args)` / `bazel.test(*args)` | `Result` with `.ok`, `.error` (all errors joined), `.errors`, `.phase` (`loading`, `analysis`, `execution`, `done`), `.targets`, `.tests` (labels `bazel test` would run) |
| `bazel.run_command("bazel query //...")` | `Result` with `.output` formatted like Bazel |
| `bazel.packages()` | `["//", "//app", ...]` |
| `bazel.printed()` | lines printed by `print()` during loading |

### Labs (graded by real Bazel)

On the page:

```html
<div class="lab" data-id="m03-lab1" data-title="Run a real py_test">
  <div class="lab-prompt"><p>What to build and why it needs real Bazel…</p><ul class="checklist" data-id="m03-lab1-steps">…</ul></div>
  <details class="hint"><summary>Hint</summary>…</details>
  <details class="solution"><summary>Show solution</summary>…</details>
</div>
```

The widget adds the `pixi run start m03-lab1` / `pixi run grade m03-lab1` commands and a "passed" toggle.
In the repository, `labs/m03-lab1/`:

```text
lab.toml        id = "m03-lab1"; title = "…"; module = "m03"
starter/        a complete Bazel workspace: .bazelversion (9.3.2), MODULE.bazel, BUILD files, sources
solution/       the same workspace, finished
grading/        optional: files laid over the workspace before grading (extra tests the learner never edits)
checks.toml     the checks, run in order in build/labs/<id>-<source>/
```

```toml
[[check]]
name = "the binary prints a greeting"
command = ["run", "//app:hello"]
expect = "success"                 # success | failure | any
stdout_contains = ["Hello, Bazel!"]
message = "Run `pixi run bazel run //app:hello` in work/m03-lab1 and compare."

[[check]]
name = "every test passes"
command = ["test", "//...", "--test_output=errors"]

[[check]]
name = "the library is private to //app"
command = ["build", "//other:uses_lib"]
expect = "failure"
output_contains = ["is not visible from"]
```

Keys: `name`, `command` (Bazel arguments), `expect`, `stdout_contains`, `stdout_lacks`, `stdout_equals`,
`stdout_lines` (exact set of lines), `output_contains`, `output_lacks`, `output_matches` (regexes over
stdout + stderr), `file_exists`, `file_contains` (`{path = "text"}`), `message` (shown on failure). Put grading
targets (for example a `py_test` that imports the learner's library, or a BUILD package that tries to depend on
something private) in `grading/`. Keep starters runnable: they should build, or fail only in the way the lab
asks the learner to fix. Use Python 3.13 and only the module versions above.

`pixi run check-labs <id>` grades the solution (must pass) and the starter (must fail at least one check). The
first run of a lab downloads Bazel, the Python toolchain, and module archives (a minute or two); later runs use
the shared repository cache.

### Quizzes

```html
<div class="quiz" data-id="m03-quiz">
<script type="application/json">
{"title": "rules_python quiz", "passScore": 0.7, "questions": [
  {"type": "single", "prompt": "HTML allowed", "code": "optional code shown above options", "lang": "starlark", "options": ["a", "b"], "answer": 1, "explanation": "<p>Why.</p>"},
  {"type": "multi", "prompt": "…", "options": ["…", "…", "…"], "answer": [0, 2], "explanation": "…"},
  {"type": "output", "prompt": "What does bazel query print?", "code": "…", "answer": "//app:hello\n//lib:greet", "explanation": "…"},
  {"type": "text", "prompt": "Which file pins the Bazel version?", "answer": [".bazelversion"], "explanation": "…"}
]}
</script>
</div>
```

Strict JSON. `answer` is an index (`single`), a list of indexes (`multi`), or the exact text / accepted list
(`output`, `text`; `text` is case-insensitive). `lang` sets the code highlighting (default `python`; use
`starlark`, `bash`, or `none`). Every question needs an `explanation` that teaches. Include "does this load?" and
"what does this query return?" questions.

### Callouts, layout, visualizers

```html
<aside class="callout note|tip|warn|danger|think|pro|pixi|bazel|python|sim"><p>…</p></aside>
<aside class="callout note" data-title="Custom heading"><p>…</p></aside>
<div class="two-col">…</div>   <div class="card-grid"><div class="card"><h4>…</h4>…</div></div>
<div class="tabs"><div class="tab" data-label="Python">…</div><div class="tab" data-label="Bazel">…</div></div>
<details class="reveal"><summary>Reveal</summary>…</details>
<ul class="checklist" data-id="m03-steps">…</ul>      (persisted checkboxes; unique data-id)
<pre class="mermaid">flowchart LR; A-->B</pre>
<div class="flashcards" data-title="Review"><script type="application/json">[{"front": "…", "back": "…"}]</script></div>
<div class="viz" data-viz="phases"></div>
<div class="viz" data-viz="buildgraph" data-config='{"title": "…", "nodes": [{"id": "a.py", "kind": "file", "x": 0, "y": 0}, {"id": "//lib:a", "kind": "rule", "x": 1, "y": 0, "deps": ["a.py"]}]}'></div>
```

`callout python` ("From Python") opens a comparison; `callout bazel` flags Bazel 9 specifics; `callout sim` says
where the simulator stops and real Bazel takes over; `callout pixi` for Pixi notes; `callout pro` for team
habits (BUILD formatting with buildifier, review conventions, CI flags). `buildgraph` nodes: `kind` is `file`,
`rule`, or `test`; `x` is the column (0–2), `y` the row; clicking a file shows what rebuilds.

Inline SVG diagrams use CSS variables for color (`fill="var(--viz-1)"`, `stroke="var(--fg-muted)"`).
