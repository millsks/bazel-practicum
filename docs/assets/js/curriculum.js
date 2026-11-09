/* Curriculum manifest. The object below must stay valid JSON: practicum check-site parses it. */
window.CURRICULUM = {
  "title": "Bazel Practicum",
  "bazel": "9.3",
  "parts": [
    {
      "id": "part0",
      "number": 0,
      "title": "Orientation",
      "level": "Start here",
      "summary": "Why Bazel, how the in-page simulator and the local labs work, and getting Bazel 9 running through Pixi.",
      "modules": [
        {
          "id": "m00",
          "title": "How This Practicum Works",
          "href": "modules/m00-orientation.html",
          "minutes": 60,
          "summary": "What Bazel is for, the simulator and the labs, installing Bazelisk with Pixi, and your first real build."
        }
      ],
      "projects": []
    },
    {
      "id": "part1",
      "number": 1,
      "title": "Stage 1 · Foundations",
      "level": "Level 1 · Building with Bazel",
      "summary": "Workspaces, packages and labels; the build graph and caching; Python with rules_python; and third-party dependencies with Bzlmod.",
      "modules": [
        {
          "id": "m01",
          "title": "Workspaces, Packages & Targets",
          "href": "modules/m01-workspaces-targets.html",
          "minutes": 120,
          "summary": "MODULE.bazel, BUILD files, packages, labels, target patterns, and bazel build, run, and test."
        },
        {
          "id": "m02",
          "title": "The Build Graph & Caching",
          "href": "modules/m02-build-graph.html",
          "minutes": 150,
          "summary": "Dependencies and visibility, loading, analysis and execution, actions, hermeticity, and why rebuilds are fast."
        },
        {
          "id": "m03",
          "title": "Python with rules_python",
          "href": "modules/m03-rules-python.html",
          "minutes": 150,
          "summary": "py_library, py_binary and py_test, imports and runfiles, data files, and the hermetic Python toolchain."
        },
        {
          "id": "m04",
          "title": "Third-Party Dependencies with Bzlmod",
          "href": "modules/m04-bzlmod-pypi.html",
          "minutes": 150,
          "summary": "bazel_dep and the Bazel Central Registry, module extensions, pip.parse and lock files, and MODULE.bazel.lock."
        }
      ],
      "projects": []
    },
    {
      "id": "part2",
      "number": 2,
      "title": "Stage 2 · Growing the Monorepo",
      "level": "Level 1 · Building with Bazel",
      "summary": "Tests at scale, configuration and select(), Go as a second language, generated files and macros, and querying the graph.",
      "modules": [
        {
          "id": "m05",
          "title": "Testing at Scale",
          "href": "modules/m05-testing.html",
          "minutes": 120,
          "summary": "Test sizes, tags and filters, test_suite, cached results, flaky tests, sharding, and reading test logs."
        },
        {
          "id": "m06",
          "title": "Configuration, Flags & select()",
          "href": "modules/m06-configuration.html",
          "minutes": 150,
          "summary": ".bazelrc and --config, compilation modes, config_setting, select(), custom build settings, and platforms."
        },
        {
          "id": "m07",
          "title": "Go: A Second Language",
          "href": "modules/m07-rules-go.html",
          "minutes": 150,
          "summary": "rules_go and the hermetic Go SDK, go_library, go_binary and go_test, and a Python test that runs a Go tool."
        },
        {
          "id": "m08",
          "title": "Generated Files & Macros",
          "href": "modules/m08-genrules-macros.html",
          "minutes": 150,
          "summary": "genrule and $(location), run_binary and write_file, diff_test, and Starlark macros in .bzl files."
        },
        {
          "id": "m09",
          "title": "Query & Debugging",
          "href": "modules/m09-query-debugging.html",
          "minutes": 120,
          "summary": "query, cquery and aquery; rdeps, somepath and allpaths; finding affected tests; and explaining a rebuild."
        }
      ],
      "projects": [
        {
          "id": "c1",
          "title": "Capstone 1: Polyglot Monorepo",
          "href": "projects/c1-polyglot-monorepo.html",
          "summary": "Grow a Python service and a Go CLI into one monorepo with shared generated data, tests, configs, and visibility rules, graded by real Bazel."
        }
      ]
    }
  ],
  "reference": [
    {
      "id": "ref-roadmap",
      "title": "Roadmap: Levels 2-3",
      "href": "reference/roadmap.html",
      "summary": "What comes after Level 1: toolchains, remote caching and execution, and writing your own rules."
    },
    {
      "id": "ref-python-to-bazel",
      "title": "Python to Bazel Cheat Sheet",
      "href": "reference/python-to-bazel.html",
      "summary": "pip, pytest, pyproject and python -m, side by side with their Bazel equivalents."
    },
    {
      "id": "ref-commands",
      "title": "Command Reference",
      "href": "reference/commands.html",
      "summary": "The bazel commands, flags, and query functions used in the course, with what each is for."
    },
    {
      "id": "ref-glossary",
      "title": "Glossary",
      "href": "reference/glossary.html",
      "summary": "Terms used in the course, with links to where each is taught."
    }
  ]
};
