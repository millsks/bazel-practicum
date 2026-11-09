"""The Bazel simulator (docs/assets/py/minibazel.py). Expected texts were captured from real Bazel 9.3.2 runs."""

import textwrap
from types import ModuleType
from typing import Any

import pytest

from practicum.sim import load_simulator
from tests.conftest import REPO_ROOT

mb: Any = load_simulator(REPO_ROOT / "docs")

MODULE = textwrap.dedent(
    """
    module(name = "demo")

    bazel_dep(name = "rules_python", version = "2.4.6")
    bazel_dep(name = "rules_go", version = "0.65.0")
    bazel_dep(name = "rules_shell", version = "0.8.0")
    bazel_dep(name = "bazel_skylib", version = "1.9.2")
    bazel_dep(name = "platforms", version = "1.1.0")
    """
)
PY = 'load("@rules_python//python:defs.bzl", "py_binary", "py_library", "py_test")\n'
GO = 'load("@rules_go//go:def.bzl", "go_binary", "go_library", "go_test")\n'
FLAGS = 'load("@bazel_skylib//rules:common_settings.bzl", "bool_flag", "string_flag")\n'


def ws(files: dict[str, str], module: str = MODULE) -> Any:
    """A simulator over ``files`` (dedented) plus a MODULE.bazel."""
    return mb.Bazel({"MODULE.bazel": module, **{k: textwrap.dedent(v) for k, v in files.items()}})


def build_error(files: dict[str, str], *args: str) -> str:
    result = ws(files).build(*(args or ("//...",)))
    assert not result.ok, result.output
    return str(result.error)


def test_module_is_the_simulator() -> None:
    assert isinstance(mb, ModuleType)
    assert mb.BAZEL_VERSION == "9.3.2"
    assert mb.load_workspace({"MODULE.bazel": ""}).packages() == []


# ----------------------------------------------------------------------------------------------- labels


@pytest.mark.parametrize(
    ("text", "package", "expected"),
    [
        ("//app:hello", "", ("", "app", "hello")),
        ("//app", "", ("", "app", "app")),
        ("//app/sub", "", ("", "app/sub", "sub")),
        (":hello", "app", ("", "app", "hello")),
        ("hello.py", "app", ("", "app", "hello.py")),
        ("data/x.txt", "app", ("", "app", "data/x.txt")),
        ("@pypi//requests", "", ("pypi", "requests", "requests")),
        ("@@rules_python//python:defs.bzl", "", ("rules_python", "python", "defs.bzl")),
        ("@platforms", "", ("platforms", "", "platforms")),
        ("//:root", "", ("", "", "root")),
    ],
)
def test_parse_label(text: str, package: str, expected: tuple[str, str, str]) -> None:
    label = mb.parse_label(text, package)
    assert (label.repo, label.package, label.name) == expected


def test_label_str_and_is_main() -> None:
    assert str(mb.parse_label("//a:b")) == "//a:b"
    assert str(mb.parse_label("@pypi//six")) == "@pypi//six:six"
    assert mb.parse_label("//a:b").is_main
    assert not mb.parse_label("@x//a:b").is_main


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty package-relative label"),
        ("//a:b:c", "target names may not contain ':'"),
        ("//a/:b", "invalid package name 'a/'"),
        ("//a/../b:c", "invalid package name"),
        ("//a:", "empty target name"),
        ("//a:/b", "invalid target name '/b'"),
        ("//a:b/../c", "invalid target name"),
        ("//a:b c", "invalid target name 'b c'"),
    ],
)
def test_parse_label_errors(text: str, message: str) -> None:
    with pytest.raises(mb.BazelError, match="invalid label|" + message) as info:
        mb.parse_label(text)
    assert message in str(info.value)


def test_parse_label_rejects_non_strings() -> None:
    with pytest.raises(mb.BazelError, match="expected a label string, got int"):
        mb.parse_label(3)


# ---------------------------------------------------------------------------------------------- loading


def test_no_module_bazel() -> None:
    bazel = mb.Bazel({"app/BUILD.bazel": ""})
    result = bazel.build("//...")
    assert result.phase == "loading"
    assert "only supported from within a workspace (below a directory having a MODULE.bazel file)" in result.error
    with pytest.raises(mb.BazelError, match=r"MODULE\.bazel"):
        bazel.query("//...")


def test_missing_load_names_the_file_to_load() -> None:
    error = build_error({"app/BUILD.bazel": 'py_binary(name = "x", srcs = ["x.py"])\n'})
    assert (
        error
        == (
            "Skipping '//...': error loading package 'app': app/BUILD.bazel:1:1: name 'py_binary' is not defined "
            '(load it with load("@rules_python//python:defs.bzl", "py_binary"))'
        )
        or "name 'py_binary' is not defined" in error
    )


def test_missing_load_fails_build_in_loading_phase() -> None:
    result = ws({"app/BUILD.bazel": 'go_library(name = "x")\n'}).build("//app:x")
    assert not result.ok
    assert result.phase == "loading"
    assert "name 'go_library' is not defined" in result.error
    assert 'load("@rules_go//go:def.bzl", "go_library")' in result.error


def test_unknown_name_without_hint() -> None:
    error = build_error({"app/BUILD.bazel": "x = undefined_thing\n"})
    assert "app/BUILD.bazel:1:1: name 'undefined_thing' is not defined" in error
    assert "load it" not in error


def test_load_of_unknown_symbol() -> None:
    error = build_error({"app/BUILD.bazel": 'load("@rules_python//python:defs.bzl", "py_nothing")\n'})
    assert "file '@rules_python//python:defs.bzl' does not contain symbol 'py_nothing'" in error


def test_load_from_unknown_repo() -> None:
    error = build_error({"app/BUILD.bazel": 'load("@rules_rust//rust:defs.bzl", "rust_binary")\n'})
    assert "No repository visible as '@rules_rust' from main repository" in error


def test_load_requires_bzl_extension_and_existing_file() -> None:
    assert "must reference a file with extension '.bzl'" in build_error({"a/BUILD.bazel": 'load("//a:x.txt", "y")\n'})
    assert "cannot load '//a:defs.bzl': no such file" in build_error({"a/BUILD.bazel": 'load("//a:defs.bzl", "y")\n'})


def test_load_file_unknown_to_the_simulator() -> None:
    error = build_error({"a/BUILD.bazel": 'load("@rules_python//python:other.bzl", "y")\n'})
    assert "no such file in the simulator's copy of @rules_python" in error


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ('x = f"{1}"\n', 'f-strings are not supported (use "%s" % x or "{}".format(x))'),
        ("def f():\n    pass\n", "functions may not be defined in BUILD files"),
        ("y = lambda: 1\n", "functions may not be defined in BUILD files"),
        ("for x in []:\n    pass\n", "`for` statements are not allowed in BUILD files"),
        ("if True:\n    pass\n", "`if` statements are not allowed in BUILD files"),
        ("x = 1 is 1\n", "'is' not supported, use '==' instead"),
        ("x = 1 < 2 < 3\n", "is not associative"),
        ("x = 2 ** 3\n", "syntax error at '**'"),
        ("x = {1, 2}\n", "set literals are not supported"),
        ("while True:\n    pass\n", "'while' not supported"),
        ("import os\n", "'import' not supported, use 'load' instead"),
        ("try:\n    pass\nexcept:\n    pass\n", "'try' not supported"),
        ("x = (\n", "syntax error"),
    ],
)
def test_starlark_restrictions_in_build_files(source: str, message: str) -> None:
    result = ws({"app/BUILD.bazel": source}).build("//app:all")
    assert result.phase == "loading"
    assert message in result.error


def test_comprehensions_and_conditional_expressions_are_fine() -> None:
    source = PY + 'py_library(name = "l", srcs = [n for n in ["a.py"]] if True else [])\n'
    assert ws({"app/BUILD.bazel": source, "app/a.py": ""}).build("//app:l").ok


def test_load_must_be_top_level() -> None:
    error = build_error({"a/BUILD.bazel": 'x = [load("//a:d.bzl", "y")]\n'})
    assert "load() must be a top-level statement" in error


def test_duplicate_targets() -> None:
    error = build_error({"a/BUILD.bazel": PY + 'py_library(name = "l")\npy_library(name = "l")\n'})
    assert (
        "a/BUILD.bazel:3:11: Error in py_library: py_library rule 'l' conflicts with existing py_library rule" in error
    )


def test_output_conflicting_with_a_rule() -> None:
    files = {"a/BUILD.bazel": 'filegroup(name = "out.txt")\ngenrule(name = "g", outs = ["out.txt"], cmd = "x")\n'}
    assert "generated file 'out.txt' in rule 'g' conflicts with existing filegroup rule" in build_error(files)


def test_unknown_attribute() -> None:
    error = build_error({"a/BUILD.bazel": PY + 'py_library(name = "l", bogus = 1)\n'})
    assert "//a:l: no such attribute 'bogus' in 'py_library' rule" in error


def test_missing_name_and_mandatory_attributes() -> None:
    assert "py_library rule has no 'name' attribute" in build_error({"a/BUILD.bazel": PY + "py_library()\n"})
    error = build_error({"a/BUILD.bazel": 'genrule(name = "g", cmd = "x")\n'})
    assert "missing value for mandatory attribute 'outs' in 'genrule' rule" in error


def test_attribute_type_errors() -> None:
    error = build_error({"a/BUILD.bazel": PY + 'py_library(name = "l", srcs = "a.py")\n'})
    assert "expected value of type 'list(string)' for attribute 'srcs' in 'py_library' rule" in error
    error = build_error({"a/BUILD.bazel": PY + 'py_library(name = "l", deps = [":x", ":x"])\n'})
    assert "Label '//a:x' is duplicated in the 'deps' attribute of rule 'l'" in error
    error = build_error({"a/BUILD.bazel": PY + 'py_test(name = "t", srcs = ["t.py"], shard_count = "2")\n'})
    assert "expected value of type 'int'" in error


def test_positional_arguments_rejected() -> None:
    assert "does not accept positional arguments" in build_error({"a/BUILD.bazel": 'filegroup("x")\n'})


def test_package_must_come_first() -> None:
    error = build_error({"a/BUILD.bazel": 'filegroup(name = "x")\npackage(default_visibility = [])\n'})
    assert "package() function cannot be called after any rule is declared" in error


def test_glob_matches_and_respects_subpackages() -> None:
    bazel = ws(
        {
            "a/BUILD.bazel": 'filegroup(name = "all", srcs = glob(["**/*.txt"], exclude = ["skip.txt"]))\n',
            "a/x.txt": "",
            "a/skip.txt": "",
            "a/d/y.txt": "",
            "a/sub/BUILD.bazel": "",
            "a/sub/z.txt": "",
        }
    )
    assert bazel.attr("//a:all", "srcs") == ["d/y.txt", "x.txt"]
    assert "glob pattern ['*.md'] didn't match anything" in build_error(
        {"a/BUILD.bazel": 'filegroup(name = "x", srcs = glob(["*.md"]))\n'}
    )
    assert ws({"a/BUILD.bazel": 'filegroup(name = "x", srcs = glob(["*.md"], allow_empty = True))\n'}).build("//a:x")


def test_print_and_fail_during_loading() -> None:
    bazel = ws({"a/BUILD.bazel": 'print("hello", package_name())\nfilegroup(name = "x")\n'})
    bazel.target("//a:x")
    assert bazel.printed() == ["hello a"]
    assert "Error in fail: stop here" in build_error({"a/BUILD.bazel": 'fail("stop here")\n'})


def test_type_errors_in_starlark_code() -> None:
    assert "Error:" in build_error({"a/BUILD.bazel": 'x = 1 + "a"\n'})


# ------------------------------------------------------------------------------------------- MODULE.bazel


def test_module_errors() -> None:
    bad = ws({}, module='module(name = "a")\nmodule(name = "b")\n').build("//...")
    assert "the module() directive can only be called once" in bad.error
    late = ws({}, module='bazel_dep(name = "x", version = "1")\nmodule(name = "a")\n').build("//...")
    assert "must be called before any other functions" in late.error
    dup = ws({}, module='bazel_dep(name = "x", version = "1")\nbazel_dep(name = "x", version = "2")\n')
    assert "The repo name 'x' is already being used by another bazel_dep" in dup.build("//...").error
    assert "syntax error" in ws({}, module="module(\n").build("//...").error
    assert "f-strings" in ws({}, module='x = f"{1}"\n').build("//...").error


def test_use_extension_requires_the_dep() -> None:
    module = 'pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")\n'
    assert "No repository visible as '@rules_python' from main repository" in ws({}, module=module).build("//...").error


def test_use_repo_requires_a_declared_hub() -> None:
    module = MODULE + 'pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")\nuse_repo(pip, "pypi")\n'
    error = ws({}, module=module).build("//...").error
    assert 'does not generate repository "pypi"' in error


def test_pip_parse_requires_hub_and_lock() -> None:
    base = MODULE + 'pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")\n'
    assert "missing mandatory attribute 'hub_name'" in ws({}, module=base + "pip.parse()\n").build("//...").error
    no_lock = base + 'pip.parse(hub_name = "pypi")\n'
    assert "requirements_lock" in ws({}, module=no_lock).build("//...").error


PIP_MODULE = MODULE + textwrap.dedent(
    """
    python = use_extension("@rules_python//python/extensions:python.bzl", "python")
    python.toolchain(python_version = "3.13", is_default = True)
    pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
    pip.parse(hub_name = "pypi", python_version = "3.13", requirements_lock = "//:requirements_lock.txt")
    use_repo(pip, "pypi", deps = "pypi")
    """
)
LOCK = "# comment\nsix==1.17.0 \\\n    --hash=sha256:abc\nPyYAML==6.0.2\n--index-url https://x\n"


def pip_ws(build: str) -> Any:
    return mb.Bazel(
        {"MODULE.bazel": PIP_MODULE, "requirements_lock.txt": LOCK, "BUILD.bazel": "", "p/BUILD.bazel": build}
    )


def test_pip_hub_targets_exist_only_when_pinned() -> None:
    bazel = pip_ws(PY + 'py_library(name = "ok", deps = ["@pypi//six", "@pypi//pyyaml", "@deps//six"])\n')
    assert bazel.build("//p:ok").ok
    assert bazel.ws.pip_packages("pypi") == {"six", "pyyaml"}
    assert bazel.target("@pypi//six").kind == "py_library"
    bad = pip_ws(PY + 'py_library(name = "bad", deps = ["@pypi//requests"])\n').build("//p:bad")
    assert "no such package '@@rules_python++pip+pypi//requests'" in bad.error
    assert "is not in //:requirements_lock.txt; add it to your requirements and re-lock" in bad.error
    with pytest.raises(mb.BazelError, match="no such target '@pypi//six:nope'"):
        bazel.target("@pypi//six:nope")


def test_pip_hub_not_imported_is_not_visible() -> None:
    module = MODULE + textwrap.dedent(
        """
        pip = use_extension("@rules_python//python/extensions:pip.bzl", "pip")
        pip.parse(hub_name = "pypi", requirements_lock = "//:requirements_lock.txt")
        """
    )
    bazel = mb.Bazel({"MODULE.bazel": module, "p/BUILD.bazel": PY + 'py_library(name = "x", deps = ["@pypi//six"])\n'})
    assert "No repository visible as '@pypi' from main repository" in bazel.build("//p:x").error


def test_go_sdk_and_toolchains_in_module() -> None:
    module = MODULE + textwrap.dedent(
        """
        go_sdk = use_extension("@rules_go//go:extensions.bzl", "go_sdk")
        go_sdk.download(version = "1.25.3")
        use_repo(go_sdk, "go_sdk")
        register_toolchains("//tools:all")
        single_version_override(module_name = "rules_go", version = "0.65.0")
        """
    )
    bazel = ws({}, module=module)
    assert bazel.ws.module.go_versions == ["1.25.3"]
    assert bazel.ws.module.registered_toolchains == ["//tools:all"]
    assert "go_sdk" in bazel.ws.visible_repos()


# ---------------------------------------------------------------------------------------------- analysis


def test_no_such_target_referenced_by() -> None:
    files = {"a/BUILD.bazel": PY + 'py_binary(name = "x", srcs = ["x.py"], deps = [":nope"])\n', "a/x.py": ""}
    error = build_error(files, "//a:x")
    assert (
        "a/BUILD.bazel:2:10: in deps attribute of py_binary rule //a:x: rule '//a:nope' does not exist. Since this "
        "rule was created by the macro 'py_binary', the error might have been caused by the macro implementation"
    ) in error


def test_no_such_target_in_another_package() -> None:
    files = {
        "a/BUILD.bazel": PY + 'py_binary(name = "x", srcs = ["x.py"], deps = ["//b:nope"])\n',
        "a/x.py": "",
        "b/BUILD.bazel": "",
    }
    assert (
        "a/BUILD.bazel:2:10: no such target '//b:nope': target 'nope' not declared in package 'b' defined by "
        "b/BUILD.bazel and referenced by '//a:x'"
    ) in build_error(files, "//a:x")


def test_files_in_deps_are_misplaced() -> None:
    files = {
        "a/BUILD.bazel": PY + 'py_library(name = "l", deps = [":x.py", "//b:g.py"])\n',
        "a/x.py": "",
        "b/BUILD.bazel": 'exports_files(["g.py"])\n',
        "b/g.py": "",
    }
    error = build_error(files, "//a:l")
    assert (
        "in deps attribute of py_library rule //a:l: source file '//a:x.py' is misplaced here (expected no files)"
        in error
    )
    assert "source file '//b:g.py' is misplaced here (expected no files)" in error


def test_missing_same_package_label_outside_deps_is_a_file() -> None:
    files = {"a/BUILD.bazel": 'filegroup(name = "f", srcs = [":nope"])\n'}
    result = ws(files).build("//a:f")
    assert result.phase == "execution"
    assert result.errors == ["missing input file '//a:nope'"]


def test_no_such_package() -> None:
    files = {"a/BUILD.bazel": PY + 'py_binary(name = "x", srcs = ["x.py"], deps = ["//zz:q"])\n', "a/x.py": ""}
    error = build_error(files, "//a:x")
    assert "no such package 'zz': BUILD file not found in any of the following directories." in error


def test_existing_file_not_mentioned_by_a_rule_is_not_a_target() -> None:
    files = {
        "a/BUILD.bazel": PY + 'py_binary(name = "x", srcs = ["x.py"], data = ["//b:f.txt"])\n',
        "a/x.py": "",
        "b/BUILD.bazel": "",
        "b/f.txt": "",
    }
    error = build_error(files, "//a:x")
    assert (
        "no such target '//b:f.txt': target 'f.txt' not declared in package 'b' defined by b/BUILD.bazel; however, "
        "a source file of this name exists.  (Perhaps add 'exports_files([\"f.txt\"])' to b/BUILD.bazel?) and "
        "referenced by '//a:x'"
    ) in error
    with pytest.raises(mb.BazelError, match="however, a source file of this name exists"):
        ws(files).query("//b:f.txt")


def test_label_crossing_into_a_subpackage_fails_loading() -> None:
    files = {
        "b/BUILD.bazel": 'filegroup(name = "fg", srcs = ["sub/c.txt"])\n',
        "b/sub/BUILD.bazel": "",
        "b/sub/c.txt": "",
    }
    result = ws(files).build("//b:fg")
    assert result.phase == "loading"
    assert (
        "Label '//b:sub/c.txt' is invalid because 'b/sub' is a subpackage; perhaps you meant to put the colon here: "
        "'//b/sub:c.txt'?"
    ) in result.error
    with pytest.raises(mb.BazelError, match="is a subpackage"):
        ws(files).query("//b:all")


VIS_BASE = {"a/x.py": "", "b/f.txt": ""}


def _vis(b_build: str, a_dep: str = "//b:lib", a_pkg: str = "a") -> Any:
    files = {
        **VIS_BASE,
        f"{a_pkg}/BUILD.bazel": PY + f'py_binary(name = "x", srcs = [], main = "x.py", data = ["{a_dep}"])\n',
        f"{a_pkg}/x.py": "",
        "b/BUILD.bazel": b_build,
    }
    files[f"{a_pkg}/BUILD.bazel"] = PY + f'py_binary(name = "x", srcs = ["x.py"], data = ["{a_dep}"])\n'
    return ws(files).build(f"//{a_pkg}:x")


def test_visibility_private_by_default() -> None:
    result = _vis('filegroup(name = "lib")\n')
    assert not result.ok
    assert (
        "in py_binary rule //a:x: Visibility error:\ntarget '//b:lib' is not visible from\ntarget '//a:x'\n"
        "Recommendation: modify the visibility declaration if you think the dependency is legitimate."
    ) in result.error


@pytest.mark.parametrize(
    ("visibility", "ok"),
    [
        ("//visibility:public", True),
        ("//visibility:private", False),
        ("//a:__pkg__", True),
        ("//c:__pkg__", False),
        ("//:__subpackages__", True),
        ("//a:__subpackages__", True),
        ("//c:__subpackages__", False),
    ],
)
def test_visibility_specs(visibility: str, ok: bool) -> None:
    assert _vis(f'filegroup(name = "lib", visibility = ["{visibility}"])\n').ok is ok


def test_subpackages_covers_nested_packages_only() -> None:
    files = {
        "lib/BUILD.bazel": 'filegroup(name = "p", visibility = ["//b:__subpackages__"])\n',
        "b/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
        "b/c/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
        "bc/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
    }
    assert ws(files).build("//b:u", "//b/c:u").ok
    assert not ws(files).build("//bc:u").ok


def test_package_group_with_negative_spec_anywhere() -> None:
    def group(packages: str) -> dict[str, str]:
        return {
            "lib/BUILD.bazel": f'package_group(name = "g", packages = {packages})\n'
            'filegroup(name = "p", visibility = [":g"])\n',
            "b/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
            "b/x/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
            "c/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
        }

    files = group('["//b/...", "-//b/x"]')
    assert ws(files).build("//b:u").ok
    assert not ws(files).build("//b/x:u").ok
    assert not ws(files).build("//c:u").ok
    files = group('["-//b", "//..."]')
    assert not ws(files).build("//b:u").ok
    assert ws(files).build("//c:u").ok
    assert ws(group('["public"]')).build("//c:u").ok
    assert ws(group('["//c"]')).build("//c:u").ok


def test_package_group_includes() -> None:
    files = {
        "lib/BUILD.bazel": 'package_group(name = "g", includes = [":h"])\npackage_group(name = "h", packages = ["//b"])\n'
        'filegroup(name = "p", visibility = [":g"])\n',
        "b/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
        "c/BUILD.bazel": 'filegroup(name = "u", srcs = ["//lib:p"])\n',
    }
    assert ws(files).build("//b:u").ok
    assert not ws(files).build("//c:u").ok


def test_default_visibility_applies_to_rules_and_files() -> None:
    assert _vis('package(default_visibility = ["//visibility:public"])\nfilegroup(name = "lib")\n').ok
    b_build = 'package(default_visibility = ["//a:__pkg__"])\nfilegroup(name = "fg", srcs = ["f.txt"])\n'
    assert _vis(b_build, "//b:f.txt").ok
    b_build = 'package(default_visibility = ["//c:__pkg__"])\nfilegroup(name = "fg", srcs = ["f.txt"])\n'
    assert "target '//b:f.txt' is not visible from" in _vis(b_build, "//b:f.txt").error


def test_source_files_are_private_unless_exported() -> None:
    assert (
        "target '//b:f.txt' is not visible from"
        in _vis('filegroup(name = "fg", srcs = ["f.txt"])\n', "//b:f.txt").error
    )
    assert _vis('exports_files(["f.txt"])\n', "//b:f.txt").ok
    assert not _vis('exports_files(["f.txt"], visibility = ["//c:__pkg__"])\n', "//b:f.txt").ok


def test_exports_files_errors() -> None:
    assert "must be in the current package" in build_error({"a/BUILD.bazel": 'exports_files(["//b:x"])\n'})
    error = build_error({"a/BUILD.bazel": 'filegroup(name = "x")\nexports_files(["x"])\n'})
    assert "conflicts with existing source file" in error


def test_generated_files_take_their_rules_visibility() -> None:
    gen = 'genrule(name = "g", outs = ["lib"], cmd = "touch $@", visibility = ["//a:__pkg__"])\n'
    assert _vis(gen, "//b:lib").ok
    assert not _vis('genrule(name = "g", outs = ["lib"], cmd = "touch $@")\n', "//b:lib").ok


def test_mandatory_providers() -> None:
    files = {
        "a/BUILD.bazel": PY
        + GO
        + 'py_binary(name = "x", srcs = ["x.py"], deps = [":g", ":fg"])\n'
        + 'go_library(name = "g", srcs = ["g.go"], importpath = "g", deps = [":p"])\n'
        + 'py_library(name = "p")\nfilegroup(name = "fg")\n',
        "a/x.py": "",
        "a/g.go": "",
    }
    error = build_error(files, "//a:x")
    assert (
        "in deps attribute of py_binary rule //a:x: '//a:g' does not have mandatory providers: 'PyInfo' or 'CcInfo'. "
        "Since this rule was created by the macro 'py_binary', the error might have been caused by the macro "
        "implementation"
    ) in error
    assert "'//a:fg' does not have mandatory providers" in error
    assert "in deps attribute of go_library rule //a:g: '//a:p' does not have mandatory providers: 'GoInfo'" in error


def test_providers_through_alias_and_external() -> None:
    files = {
        "a/BUILD.bazel": PY
        + 'py_library(name = "real")\nalias(name = "al", actual = ":real")\nalias(name = "broken", actual = ":gone")\n'
        + 'py_library(name = "u", deps = [":al", "@rules_python//python/runfiles"])\n',
    }
    assert ws(files).build("//a:u").ok


def test_misplaced_source_file() -> None:
    files = {
        "a/BUILD.bazel": GO + 'go_library(name = "l", srcs = ["notes.txt"], importpath = "l")\n',
        "a/notes.txt": "",
    }
    assert "source file '//a:notes.txt' is misplaced here (expected .go, .s, .S, .h, .c, .cc)" in build_error(files)


def test_py_rules_accept_any_file_in_srcs() -> None:
    files = {
        "y/BUILD.bazel": PY + 'py_binary(name = "y", srcs = ["hello.py", "c.yaml"], main = "hello.py")\n',
        "y/hello.py": "",
        "y/c.yaml": "",
    }
    assert ws(files).build("//y:y").ok


def test_testonly() -> None:
    files = {
        "a/BUILD.bazel": PY
        + 'py_library(name = "t", testonly = True)\npy_binary(name = "x", srcs = ["x.py"], deps = [":t"])\n'
        'py_test(name = "ok", srcs = ["ok.py"], deps = [":t"])\n',
        "a/x.py": "",
        "a/ok.py": "",
    }
    error = build_error(files, "//a:x")
    assert (
        "in py_binary rule //a:x: non-test target '//a:x' depends on testonly target '//a:t' and doesn't have "
        "testonly attribute set"
    ) in error
    assert ws(files).build("//a:ok").ok


def test_package_default_testonly() -> None:
    files = {"a/BUILD.bazel": PY + 'package(default_testonly = True)\npy_library(name = "t")\n'}
    assert ws(files).target("//a:t").attrs["testonly"] is True


def test_cycle() -> None:
    files = {
        "a/BUILD.bazel": PY
        + 'py_library(name = "p", deps = [":q"])\npy_library(name = "q", deps = [":r"])\npy_library(name = "r", deps = [":p"])\n'
    }
    error = build_error(files, "//a:p")
    assert (
        "a/BUILD.bazel:2:11: in py_library rule //a:p: cycle in dependency graph:\n.-> //a:p\n|   //a:q\n|   //a:r\n`-- //a:p"
        in error
    )


def test_py_binary_default_main() -> None:
    files = {"a/BUILD.bazel": PY + 'py_binary(name = "x", srcs = ["y.py"])\n', "a/y.py": ""}
    error = build_error(files, "//a:x")
    assert (
        "Error in fail: corresponding default 'x.py' does not appear in srcs. Add it or override default file name "
        "with a 'main' attribute"
    ) in error
    files["a/BUILD.bazel"] = PY + 'py_binary(name = "x", srcs = ["y.py"], main = "z.py")\n'
    assert "could not find 'z.py' as specified by 'main' attribute" in build_error(files, "//a:x")
    files["a/BUILD.bazel"] = PY + 'py_binary(name = "x", srcs = ["y.py"], main = "y.py")\n'
    assert ws(files).build("//a:x").ok
    files["a/BUILD.bazel"] = PY + 'py_binary(name = "x", srcs = ["y.py"], main_module = "pkg.y")\n'
    assert ws(files).build("//a:x").ok


def test_genrule_make_variables() -> None:
    files = {
        "g/BUILD.bazel": "genrule(name = 'ok', srcs = ['in.txt'], outs = ['out.txt'], cmd = 'cp $(location in.txt) $@ $(SRCS)')\n"
        "genrule(name = 'many', srcs = ['in.txt', 'b.txt'], outs = ['a.txt', 'c.txt'], cmd = 'cp $< $@')\n"
        "genrule(name = 'undeclared', outs = ['d.txt'], cmd = 'cat $(location :nope) > $@')\n"
        "genrule(name = 'var', outs = ['e.txt'], cmd = 'echo $(FOO) > $@')\n"
        "genrule(name = 'nocmd', outs = ['f.txt'])\n",
        "g/in.txt": "",
        "g/b.txt": "",
    }
    bazel = ws(files)
    assert bazel.build("//g:ok").ok
    many = bazel.build("//g:many").error
    assert "in cmd attribute of genrule rule //g:many: variable '$@' : more than one output file" in many
    assert "variable '$<' : more than one input file" in many
    undeclared = bazel.build("//g:undeclared").error
    assert "label '//g:nope' in $(location) expression is not a declared prerequisite of this rule" in undeclared
    assert "$(FOO) not defined" in bazel.build("//g:var").error
    assert "missing value for 'cmd'" in bazel.build("//g:nocmd").error


def test_generated_file_depends_on_its_rule() -> None:
    files = {
        "g/BUILD.bazel": "genrule(name = 'g', srcs = ['in.txt'], outs = ['out.txt'], cmd = 'cp $< $@')\n",
        "g/in.txt": "",
    }
    bazel = ws(files)
    assert bazel.query("deps(//g:out.txt)") == ["//g:g", "//g:in.txt", "//g:out.txt"]
    assert bazel.target("//g:out.txt").kind == "generated file"
    assert bazel.query('kind("generated file", //g:*)') == ["//g:out.txt"]
    assert bazel.build("//g:out.txt").ok


def test_missing_input_is_an_execution_error() -> None:
    result = ws({"a/BUILD.bazel": PY + 'py_binary(name = "x", srcs = ["x.py"])\n'}).build("//a:x")
    assert not result.ok
    assert result.phase == "execution"
    assert result.errors == ["missing input file '//a:x.py'"]
    assert "ERROR: missing input file '//a:x.py'" in result.output


def test_select_key_must_be_a_config_setting() -> None:
    files = {"a/BUILD.bazel": 'filegroup(name = "x")\nfilegroup(name = "y", srcs = select({":x": []}))\n'}
    assert "'//a:x' does not have mandatory providers: 'ConfigMatchingProvider'" in build_error(files, "//a:y")
    files = {"a/BUILD.bazel": 'filegroup(name = "y", srcs = select({":nope": [], "//conditions:default": []}))\n'}
    assert "no such target '//a:nope'" in build_error(files, "//a:y")
    with pytest.raises(mb.BazelError, match="no such target '//a:nope'"):
        ws(files).query("deps(//a:y)")


def test_select_errors_at_loading() -> None:
    assert "select({}) with an empty dictionary" in build_error(
        {"a/BUILD.bazel": 'filegroup(name = "y", srcs = select({}))\n'}
    )
    files = {"a/BUILD.bazel": 'filegroup(name = "y", tags = select({"//conditions:default": []}))\n'}
    assert "attribute 'tags' is not configurable" in build_error(files)


# ------------------------------------------------------------------------------------------------- select


SELECT_BUILD = (
    FLAGS
    + """
bool_flag(name = "prod", build_setting_default = False)
string_flag(name = "color", build_setting_default = "red", values = ["red", "blue"])
config_setting(name = "opt", values = {"compilation_mode": "opt"})
config_setting(name = "fast", define_values = {"mode": "fast"})
config_setting(name = "defined", values = {"define": "mode=slow"})
config_setting(name = "is_prod", flag_values = {":prod": "true"})
config_setting(name = "blue", flag_values = {":color": "blue"})
config_setting(name = "opt_blue", values = {"compilation_mode": "opt"}, flag_values = {":color": "blue"})
config_setting(name = "linux", constraint_values = ["@platforms//os:linux"])
config_setting(name = "py313", flag_values = {"@rules_python//python/config_settings:python_version": "3.13"})
platform(name = "win", constraint_values = ["@platforms//os:windows", "@platforms//cpu:x86_64"])
platform(name = "win_child", parents = [":win"])
filegroup(name = "d1")
filegroup(name = "d2")
filegroup(name = "d3")
filegroup(name = "a", srcs = select({":opt": [":d1"], "//conditions:default": [":d2"]}))
filegroup(name = "b", srcs = select({":fast": [":d1"], ":is_prod": [":d3"]}))
filegroup(name = "c", srcs = select({":blue": [":d1"], ":opt_blue": [":d2"], "//conditions:default": []}))
filegroup(name = "d", srcs = select({":blue": [":d1"], ":opt": [":d2"], "//conditions:default": []}))
filegroup(name = "e", srcs = select({":linux": [":d1"], "@platforms//os:windows": [":d2"]}))
filegroup(name = "f", srcs = [":d3"] + select({":defined": [":d1"], "//conditions:default": []}))
filegroup(name = "g", srcs = select({":opt": [":d1"]}, no_match_error = "build with -c opt"))
filegroup(name = "h", srcs = select({":py313": [":d1"], "//conditions:default": []}))
"""
)
RC = "build:fast --define=mode=fast\ncommon:prod --//c:prod\ncommon --//c:color=red\nquery --keep_going\n"


@pytest.fixture
def sel() -> Any:
    module = MODULE + 'python = use_extension("@rules_python//python/extensions:python.bzl", "python")\n'
    module += 'python.toolchain(python_version = "3.13", is_default = True)\n'
    return mb.Bazel({"MODULE.bazel": module, "c/BUILD.bazel": SELECT_BUILD, ".bazelrc": RC})


def test_query_reports_every_branch_and_condition(sel: Any) -> None:
    assert sel.query("deps(//c:a)") == ["//c:a", "//c:d1", "//c:d2", "//c:opt"]
    assert sel.query("labels(srcs, //c:a)") == ["//c:d1", "//c:d2"]


def test_cquery_resolves_values(sel: Any) -> None:
    assert sel.cquery("deps(//c:a)") == ["//c:a", "//c:d2", "//c:opt"]
    assert sel.cquery("deps(//c:a)", "-c", "opt") == ["//c:a", "//c:d1", "//c:opt"]
    assert sel.cquery("labels(srcs, //c:a)", "--compilation_mode=opt") == ["//c:d1"]
    assert sel.attr("//c:a", "srcs", "-c", "dbg") == [":d2"]


def test_attr_without_flags_refuses_configurable_values(sel: Any) -> None:
    with pytest.raises(mb.BazelError, match="is configurable; pass flags"):
        sel.attr("//c:a", "srcs")
    assert sel.attr("//c:d1", "srcs") is None


def test_define_values_and_bazelrc_configs(sel: Any) -> None:
    no_match = sel.build("//c:b")
    assert not no_match.ok
    assert (
        'c/BUILD.bazel:19:10: configurable attribute "srcs" in //c:b doesn\'t match this configuration. Would a '
        "default condition help?\n\nConditions checked:\n //c:fast\n //c:is_prod\n\nTo see a condition's definition, "
        "run: bazel query --output=build <condition label>."
    ) in no_match.error
    assert sel.build("//c:b", "--config=fast").ok
    assert sel.build("//c:b", "--define=mode=fast").ok
    assert sel.build("//c:b", "--define", "mode=fast").ok
    assert sel.build("//c:b", "--config=prod").ok
    assert sel.build("//c:b", "--//c:prod").ok
    assert sel.build("//c:b", "--//c:prod=true").ok
    assert not sel.build("//c:b", "--no//c:prod").ok


def test_values_define(sel: Any) -> None:
    assert sel.cquery("labels(srcs, //c:f)", "--define=mode=slow") == ["//c:d1", "//c:d3"]
    assert sel.cquery("labels(srcs, //c:f)") == ["//c:d3"]


def test_unknown_config(sel: Any) -> None:
    result = sel.build("//c:a", "--config=nope")
    assert result.phase == "options"
    assert "Config value 'nope' is not defined in any .rc file" in result.error


def test_specialization_and_ambiguity(sel: Any) -> None:
    assert sel.cquery("labels(srcs, //c:c)", "-c", "opt", "--//c:color=blue") == ["//c:d2"]
    assert sel.cquery("labels(srcs, //c:c)", "--//c:color=blue") == ["//c:d1"]
    result = sel.build("//c:d", "-c", "opt", "--//c:color=blue")
    assert (
        'Illegal ambiguous match on configurable attribute "srcs" in //c:d:\n//c:blue\n//c:opt\nMultiple'
        in result.error
    )


def test_no_match_error(sel: Any) -> None:
    assert 'configurable attribute "srcs" in //c:g doesn\'t match this configuration: build with -c opt' in (
        sel.build("//c:g").error
    )
    assert sel.build("//c:g", "-c", "opt").ok


def test_constraint_values_and_platforms(sel: Any) -> None:
    assert sel.cquery("labels(srcs, //c:e)") == ["//c:d1"]
    assert sel.cquery("labels(srcs, //c:e)", "--platforms=//c:win") == ["//c:d2"]
    assert sel.cquery("labels(srcs, //c:e)", "--platforms=//c:win_child") == ["//c:d2"]
    with pytest.raises(mb.BazelError, match="doesn't match this configuration"):
        sel.cquery("labels(srcs, //c:e)", "--host_os=darwin")
    with pytest.raises(mb.BazelError, match="does not provide PlatformInfo"):
        sel.cquery("labels(srcs, //c:e)", "--platforms=//c:d1")


def test_python_version_flag_defaults_to_the_toolchain(sel: Any) -> None:
    assert sel.cquery("labels(srcs, //c:h)") == ["//c:d1"]


def test_invalid_compilation_mode(sel: Any) -> None:
    result = sel.build("//c:a", "-c", "fast")
    assert "Not a valid compilation mode: (should be dbg, opt or fastbuild)" in result.error
    assert "Expected value after -c" in sel.build("//c:a", "-c").error


# -------------------------------------------------------------------------------------------------- query


QUERY_FILES = {
    "a/BUILD.bazel": PY
    + 'py_library(name = "l1", srcs = ["l1.py"], deps = [":l2"])\n'
    + 'py_library(name = "l2", srcs = ["l2.py"], deps = ["//b:l3"])\n'
    + 'py_binary(name = "app", srcs = ["app.py"], deps = [":l1"], tags = ["x"])\n',
    "b/BUILD.bazel": PY
    + 'py_library(name = "l3", srcs = ["l3.py"], visibility = ["//visibility:public"])\n'
    + 'py_test(name = "t", srcs = ["t.py"], deps = [":l3"], size = "small")\n',
}


@pytest.fixture
def q() -> Any:
    return ws(QUERY_FILES)


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("deps(//a:app, 1)", ["//a:app", "//a:app.py", "//a:l1"]),
        ("deps(//a:app, 2)", ["//a:app", "//a:app.py", "//a:l1", "//a:l1.py", "//a:l2"]),
        ("rdeps(//..., //b:l3)", ["//a:app", "//a:l1", "//a:l2", "//b:l3", "//b:t"]),
        ("rdeps(//..., //b:l3, 1)", ["//a:l2", "//b:l3", "//b:t"]),
        ("somepath(//a:app, //b:l3)", ["//a:app", "//a:l1", "//a:l2", "//b:l3"]),
        ("allpaths(//a:app, //b:l3)", ["//a:app", "//a:l1", "//a:l2", "//b:l3"]),
        ("somepath(//b:t, //a:app)", []),
        ("kind(py_library, //...)", ["//a:l1", "//a:l2", "//b:l3"]),
        ('kind("source file", deps(//a:app))', ["//a:app.py", "//a:l1.py", "//a:l2.py", "//b:l3.py"]),
        ("kind(rule, //b:*)", ["//b:l3", "//b:t"]),
        ("attr(tags, x, //...)", ["//a:app"]),
        ("attr(size, small, //...)", ["//b:t"]),
        ("attr(testonly, 1, //...)", ["//b:t"]),
        ('attr(deps, "//b:l3", //...)', ["//a:l2", "//b:t"]),
        ('filter("l[12]", //...)', ["//a:l1", "//a:l2"]),
        ("labels(deps, //a:app)", ["//a:l1"]),
        ("labels(srcs, //a:l1 + //a:l2)", ["//a:l1.py", "//a:l2.py"]),
        ("labels(nonexistent, //a:app)", []),
        ("tests(//...)", ["//b:t"]),
        ("set(//a:l1 //b:t)", ["//a:l1", "//b:t"]),
        ("siblings(//b:t)", ["//b:BUILD.bazel", "//b:l3", "//b:l3.py", "//b:t", "//b:t.py"]),
        ("buildfiles(//a:app)", ["//a:BUILD.bazel"]),
        ("same_pkg_direct_rdeps(//a:l2)", ["//a:l1"]),
        ("//... - //a:all", ["//b:l3", "//b:t"]),
        ("//a:all ^ kind(py_binary, //...)", ["//a:app"]),
        ("//a:l1 + //b:t", ["//a:l1", "//b:t"]),
        ("//a:all intersect //a:app", ["//a:app"]),
        ("//a:all except //a:app", ["//a:l1", "//a:l2"]),
        ("//a:all union //b:t", ["//a:app", "//a:l1", "//a:l2", "//b:t"]),
        ("(//a:l1 + //a:l2) - //a:l2", ["//a:l1"]),
        ("a:app", ["//a:app"]),
    ],
)
def test_query_functions(q: Any, expr: str, expected: list[str]) -> None:
    assert q.query(expr) == expected


def test_allrdeps_needs_a_universe(q: Any) -> None:
    with pytest.raises(mb.BazelError, match="unknown function 'allrdeps' at 'allrdeps \\( //b:l3'"):
        q.query("allrdeps(//b:l3)")
    assert q.query("allrdeps(//b:l3)", "--universe_scope=//...") == ["//a:app", "//a:l1", "//a:l2", "//b:l3", "//b:t"]
    assert q.query("allrdeps(//b:l3, 1)", "--universe_scope=//...") == ["//a:l2", "//b:l3", "//b:t"]
    assert q.query("allrdeps(//b:l3)", "--infer_universe_scope") == ["//b:l3"]


def test_query_errors(q: Any) -> None:
    with pytest.raises(mb.BazelError, match="expected one of \\['allpaths', 'attr', 'buildfiles'"):
        q.query("nosuch(//a:app)")
    with pytest.raises(mb.BazelError, match="syntax error"):
        q.query("deps(//a:app")
    with pytest.raises(mb.BazelError, match="syntax error"):
        q.query("deps()")
    with pytest.raises(mb.BazelError, match="syntax error at"):
        q.query("//a:app )")
    with pytest.raises(mb.BazelError, match="syntax error at '\\+'"):
        q.query("+ //a:app")
    with pytest.raises(mb.BazelError, match="syntax error in set"):
        q.query("set(//a:app, //b:t)")
    with pytest.raises(mb.BazelError, match="premature end"):
        q.query("//a:app +")
    with pytest.raises(mb.BazelError, match="no targets found beneath 'zz'"):
        q.query("//zz/...")
    with pytest.raises(mb.BazelError, match="no such target '//a:nope'"):
        q.query("//a:nope")


def test_query_function_not_simulated(q: Any) -> None:
    with pytest.raises(mb.BazelError, match="does not implement the query function 'visible'"):
        q.query("visible(//a:app, //b:t)")


# ------------------------------------------------------------------------------------------------ patterns


PATTERN_FILES = {
    "a/BUILD.bazel": PY
    + 'py_library(name = "lib", srcs = ["lib.py"])\n'
    + 'py_test(name = "t", srcs = ["t.py"])\n'
    + 'py_test(name = "m", srcs = ["m.py"], tags = ["manual"])\n',
    "a/sub/BUILD.bazel": 'filegroup(name = "s", srcs = ["data.txt"])\n',
    "other/BUILD.bazel": 'filegroup(name = "o")\n',
    "a/sub/data.txt": "",
}


@pytest.fixture
def pats() -> Any:
    return ws(PATTERN_FILES)


def test_target_patterns_in_query(pats: Any) -> None:
    assert pats.query("//...") == ["//a:lib", "//a:m", "//a:t", "//a/sub:s", "//other:o"]
    assert pats.query("//a/...") == ["//a:lib", "//a:m", "//a:t", "//a/sub:s"]
    assert pats.query("//a:all") == ["//a:lib", "//a:m", "//a:t"]
    assert pats.query("//a:*") == ["//a:BUILD.bazel", "//a:lib", "//a:lib.py", "//a:m", "//a:m.py", "//a:t", "//a:t.py"]
    assert pats.query("//a:all-targets") == pats.query("//a:*")
    assert "//a/sub:data.txt" in pats.query("//a/...:*")
    assert pats.packages() == ["//a", "//a/sub", "//other"]


def test_build_skips_manual_targets_and_honours_exclusions(pats: Any) -> None:
    files = {**PATTERN_FILES, "a/lib.py": "", "a/t.py": "", "a/m.py": ""}
    bazel = ws(files)
    assert bazel.build("//...").targets == ["//a/sub:s", "//a:lib", "//a:t", "//other:o"]
    assert bazel.build("//a:all").targets == ["//a:lib", "//a:t"]
    assert bazel.build("--", "//...", "-//a/...").targets == ["//other:o"]
    assert len(bazel.build("--", "-//a/...", "//...").targets) == 4  # patterns apply left to right
    invalid = bazel.build("//...", "-//a/...")
    assert invalid.phase == "options"
    assert invalid.output == "ERROR: Invalid options syntax: -//a/..."
    assert bazel.build("--", "//...", "-//a:t").targets == ["//a/sub:s", "//a:lib", "//other:o"]
    assert bazel.build("//a:m").targets == ["//a:m"]


def test_build_with_no_targets_and_bad_patterns(pats: Any) -> None:
    result = pats.build()
    assert "No targets specified" in result.error
    bad = pats.build("//zz/...")
    assert not bad.ok
    assert "Skipping '//zz/...': no targets found beneath 'zz'" in bad.output


# -------------------------------------------------------------------------------------------- bazel test


TEST_FILES = {
    "t/BUILD.bazel": PY
    + 'py_test(name = "s", srcs = ["s.py"], size = "small")\n'
    + 'py_test(name = "l", srcs = ["l.py"], size = "large", tags = ["slow"])\n'
    + 'py_test(name = "m", srcs = ["m.py"], tags = ["manual"])\n'
    + 'py_test(name = "d", srcs = ["d.py"])\n'
    + 'py_library(name = "lib", srcs = ["lib.py"])\n'
    + 'test_suite(name = "all_tests")\n'
    + 'test_suite(name = "fast", tags = ["-slow"])\n'
    + 'test_suite(name = "man", tests = [":m", ":s"])\n'
    + 'test_suite(name = "nested", tests = [":man", ":l"])\n'
    + 'test_suite(name = "wrong", tests = [":lib"], tags = ["manual"])\n',
    **{f"t/{n}.py": "" for n in ("s", "l", "m", "d", "lib")},
}


@pytest.fixture
def tests_ws() -> Any:
    return ws(TEST_FILES)


def test_bazel_test_selects_non_manual_tests(tests_ws: Any) -> None:
    result = tests_ws.test("//...")
    assert result.ok
    # //t:man lists the manual test explicitly, and //... includes //t:man, so //t:m runs too (as in Bazel 9.3.2)
    assert result.tests == ["//t:d", "//t:l", "//t:m", "//t:s"]
    assert "//t:lib" in result.targets
    assert ws({**TEST_FILES, "t/BUILD.bazel": TEST_FILES["t/BUILD.bazel"].split("test_suite")[0]}).test(
        "//..."
    ).tests == [
        "//t:d",
        "//t:l",
        "//t:s",
    ]
    assert "Executed 0 out of 4 tests (the simulator analyzes; it does not run tests)." in result.output


def test_test_suites(tests_ws: Any) -> None:
    assert tests_ws.query("tests(//t:all_tests)") == ["//t:d", "//t:l", "//t:s"]
    assert tests_ws.query("tests(//t:fast)") == ["//t:d", "//t:s"]
    assert tests_ws.query("tests(//t:man)") == ["//t:m", "//t:s"]
    assert tests_ws.query("tests(//t:nested)") == ["//t:l", "//t:m", "//t:s"]
    assert tests_ws.test("//t:man").tests == ["//t:m", "//t:s"]
    assert "expecting a test or a test_suite rule but '//t:lib' is not one" in tests_ws.build("//t:wrong").error


def test_tag_and_size_filters(tests_ws: Any) -> None:
    assert tests_ws.test("//...", "--test_tag_filters=-slow").tests == ["//t:d", "//t:m", "//t:s"]
    assert tests_ws.test("//...", "--test_tag_filters=slow").tests == ["//t:l"]
    assert tests_ws.test("//...", "--test_tag_filters=small").tests == ["//t:s"]
    assert tests_ws.test("//...", "--test_size_filters=small,large").tests == ["//t:l", "//t:s"]
    assert tests_ws.test("//...", "--test_size_filters=medium").tests == ["//t:d", "//t:m"]


def test_build_tests_only(tests_ws: Any) -> None:
    result = tests_ws.test("//...", "--build_tests_only", "--keep_going")
    assert result.targets == ["//t:d", "//t:l", "//t:m", "//t:s"]


def test_no_tests_found(tests_ws: Any) -> None:
    result = tests_ws.test("//t:lib")
    assert not result.ok
    assert result.error == "No test targets were found, yet testing was requested"


# ---------------------------------------------------------------------------------------------- .bzl macros


MACRO_FILES = {
    "m/BUILD.bazel": 'load(":defs.bzl", "pair", renamed = "pair")\npair(name = "p")\nrenamed(name = "q")\n',
    "m/defs.bzl": textwrap.dedent(
        """
        load("@rules_python//python:defs.bzl", "py_library")
        load("//tools:helpers.bzl", "suffix")

        _PRIVATE = "x"

        def pair(name):
            py_library(name = name + suffix(), srcs = [])
            native.filegroup(name = name + "_b", srcs = [":" + name + suffix()])
            print("made", native.package_name())
        """
    ),
    "tools/BUILD.bazel": "",
    "tools/helpers.bzl": 'def suffix():\n    return "_a"\n',
}


def test_macros_declare_targets_in_the_calling_package() -> None:
    bazel = ws(MACRO_FILES)
    assert bazel.query("//m:all") == ["//m:p_a", "//m:p_b", "//m:q_a", "//m:q_b"]
    assert bazel.build("//m:all").ok
    assert bazel.printed() == ["made m", "made m"]


def test_private_symbols_cannot_be_loaded() -> None:
    files = {**MACRO_FILES, "m/BUILD.bazel": 'load(":defs.bzl", "_PRIVATE")\n'}
    assert "symbol '_PRIVATE' is private and cannot be imported" in build_error(files)


def test_bzl_rules_restrictions() -> None:
    files = {"m/BUILD.bazel": 'load(":d.bzl", "x")\n', "m/d.bzl": "for i in []:\n    pass\n"}
    assert "for loops are not allowed at the top level" in build_error(files)
    files["m/d.bzl"] = "if True:\n    pass\n"
    assert "if statements are not allowed at the top level" in build_error(files)
    files["m/d.bzl"] = "def f(:\n"
    assert "syntax error" in build_error(files)


def test_bzl_in_a_directory_that_is_not_a_package() -> None:
    files = {"m/BUILD.bazel": 'load("//m:sub/d.bzl", "x")\n', "m/sub/d.bzl": "x = 1\n", "m/sub/BUILD.bazel": ""}
    assert "is not a package" in build_error(files, "//m:all")


def test_load_cycle() -> None:
    files = {
        "m/BUILD.bazel": 'load(":a.bzl", "x")\n',
        "m/a.bzl": 'load(":b.bzl", "y")\nx = 1\n',
        "m/b.bzl": 'load(":a.bzl", "x")\ny = 1\n',
    }
    assert "cycle in load graph" in build_error(files, "//m:all")


def test_existing_rules_and_native_helpers() -> None:
    files = {
        "m/BUILD.bazel": 'load(":d.bzl", "check")\nfilegroup(name = "fg")\ncheck()\n',
        "m/d.bzl": textwrap.dedent(
            """
            def check():
                if native.existing_rule("fg")["kind"] != "filegroup" or native.existing_rule("nope") != None:
                    fail("bad")
                if sorted(native.existing_rules().keys()) != ["fg"]:
                    fail("bad keys")
                native.filegroup(name = "ok", srcs = native.glob(["*.txt"], allow_empty = True))
            """
        ),
    }
    assert ws(files).query("//m:all") == ["//m:fg", "//m:ok"]


# -------------------------------------------------------------------------------------------- run_command


def test_run_command_query_formats(q: Any) -> None:
    assert q.run_command("bazel query 'deps(//a:app, 1)'").output == "//a:app\n//a:app.py\n//a:l1"
    kinds = q.run_command("bazel query //a:all --output=label_kind").output
    assert kinds.splitlines() == ["py_binary rule //a:app", "py_library rule //a:l1", "py_library rule //a:l2"]
    assert q.run_command("pixi run bazel query //... --output=package").output == "a\nb"
    assert q.run_command("bazel query 'kind(go_library, //...)'").output == "INFO: Empty results"
    assert q.run_command("bazel query //... --output=xml").errors
    assert q.run_command("bazel query //a:app //b:t").errors == [
        "query expects exactly one query expression (quote it)"
    ]
    assert q.run_command("bazel query 'allrdeps(//b:l3)' --universe_scope=//...").ok


def test_run_command_cquery_with_separate_flag_values(sel: Any) -> None:
    result = sel.run_command("bazel cquery 'deps(//c:a)' -c opt")
    assert result.ok
    assert result.targets == ["//c:a", "//c:d1", "//c:opt"]
    assert sel.run_command("bazel cquery 'labels(srcs, //c:e)' --platforms //c:win").targets == ["//c:d2"]


def test_run_command_build_test_and_run() -> None:
    files = {
        "a/BUILD.bazel": PY + 'py_binary(name = "x", srcs = ["x.py"])\nfilegroup(name = "fg")\n'
        'py_test(name = "t", srcs = ["t.py"])\n',
        "a/x.py": "",
        "a/t.py": "",
    }
    bazel = ws(files)
    built = bazel.run_command("bazel build //a:x")
    assert built.output == (
        "INFO: Analyzed 1 target (simulated).\n"
        "INFO: Build completed successfully (analysis only: the simulator does not run actions)."
    )
    assert "INFO: Analyzed 3 targets (simulated)." in bazel.run_command("bazel build //a:all").output
    tested = bazel.run_command("bazel test //...").output
    assert "//a:t" in tested and "(would run)" in tested
    ran = bazel.run_command("bazel run //a:x")
    assert ran.output.endswith("INFO: Running command line: bazel-bin/a/x (simulated: not executed)")
    assert bazel.run_command("bazel run //a:fg").errors == ["Cannot run target //a:fg: Not executable"]
    assert not bazel.run_command("bazel run").ok


def test_run_command_misc() -> None:
    bazel = ws({})
    assert bazel.run_command("bazel version").output == "Bazel 9.3.2 (simulated)"
    assert "does nothing in the simulator" in bazel.run_command("bazel clean").output
    assert bazel.run_command("bazel frobnicate").output == "Command 'frobnicate' not found. Try 'bazel help'."
    assert bazel.run_command("bazel").output == "Usage: bazel <command> <options> ..."
    assert bazel.run_command("bazel query 'unclosed").errors
    assert bazel.run_command("bazel query //nope:x").output.startswith("ERROR: no such package 'nope'")


def test_build_output_lists_errors_like_bazel() -> None:
    files = {"a/BUILD.bazel": PY + 'py_library(name = "l", deps = [":nope"])\n'}
    output = ws(files).run_command("bazel build //a:l").output
    assert output.splitlines()[-2:] == [
        "ERROR: Analysis of target failed; build aborted",
        "ERROR: Build did NOT complete successfully",
    ]


def test_target_and_exists_and_result_helpers() -> None:
    bazel = ws({"a/BUILD.bazel": PY + 'py_library(name = "l", srcs = ["l.py"], tags = ["x"])\n', "a/l.py": ""})
    target = bazel.target("//a:l")
    assert target.kind == "py_library"
    assert target.tags == ["x"]
    assert str(target) == "//a:l"
    assert repr(target) == "<py_library rule //a:l>"
    assert target.name == "l"
    assert target.rule_class is mb.RULES["py_library"]
    assert bazel.target("//a:l.py").kind_string() == "source file"
    assert bazel.target("//a:l.py").tags == []
    assert bazel.exists("//a:l")
    assert not bazel.exists("//a:nope")
    assert not bazel.exists("//zz:nope")
    result = bazel.build("//a:l")
    assert bool(result) is True
    assert result.error == ""


def test_external_targets() -> None:
    bazel = ws({})
    assert bazel.target("@platforms//os:linux").kind == "constraint_value"
    assert bazel.target("@rules_python//python:defs.bzl").kind == "source file"
    assert bazel.target("@rules_go//go/tools:anything").kind == "external target"
    with pytest.raises(mb.BazelError, match="No repository visible as '@nope' from main repository"):
        bazel.target("@nope//x:y")


# ------------------------------------------------------------------------------------------------ run_checks


def test_run_checks_reports_pass_fail_and_errors() -> None:
    files = {"MODULE.bazel": MODULE, "a/BUILD.bazel": PY + 'py_library(name = "l")\n'}
    checks = textwrap.dedent(
        """
        def test_passes(bazel):
            assert bazel.target("//a:l").kind == "py_library"

        def test_fails_with_message(bazel):
            assert False, "explain why"

        def test_fails_without_message(bazel):
            assert False

        def test_bazel_error(bazel):
            bazel.target("//a:nope")

        def test_other_exception(bazel):
            raise ValueError("odd")

        def helper(bazel):
            raise AssertionError("never run")
        """
    )
    results = mb.run_checks(files, checks)
    assert [(r["name"], r["ok"]) for r in results] == [
        ("passes", True),
        ("fails with message", False),
        ("fails without message", False),
        ("bazel error", False),
        ("other exception", False),
    ]
    assert results[1]["msg"] == "explain why"
    assert results[2]["msg"] == "assertion failed"
    assert results[3]["msg"].startswith("Bazel reported an error: no such target '//a:nope'")
    assert results[4]["msg"] == "ValueError: odd"


def test_run_checks_gives_each_check_a_fresh_workspace() -> None:
    files = {"MODULE.bazel": MODULE, "a/BUILD.bazel": 'print("loaded")\nfilegroup(name = "x")\n'}
    checks = "def test_one(bazel):\n    bazel.target('//a:x')\n    assert bazel.printed() == ['loaded']\n\n"
    checks += "def test_two(bazel):\n    assert bazel.printed() == []\n"
    assert all(r["ok"] for r in mb.run_checks(files, checks))


# --------------------------------------------------------------------- regressions verified against Bazel 9.3.2


def test_unknown_options_are_rejected() -> None:
    files = {"app/BUILD.bazel": PY + 'py_binary(name = "cli", srcs = ["cli.py"])\n', "app/cli.py": ""}
    bazel = ws(files)
    assert bazel.run_command("bazel run //app:cli --name Ada").output == "ERROR: --name :: Unrecognized option: --name"
    assert bazel.run_command("bazel build //app:cli -x").output == "ERROR: -x :: Unrecognized option: -x"
    assert bazel.run_command("bazel run //app:cli -- --name Ada").ok
    ok = "bazel build //app:cli --keep_going --nokeep_going --verbose_failures --test_output errors --nobuild"
    assert bazel.run_command(ok).ok


def test_query_subtraction_without_space_and_sort_order() -> None:
    files = {
        "lib/BUILD.bazel": 'filegroup(name = "l")\n',
        "tools/BUILD.bazel": 'filegroup(name = "gen")\n',
        "tools/exp/BUILD.bazel": 'filegroup(name = "x")\n',
    }
    bazel = ws(files)
    assert bazel.query("//...") == ["//lib:l", "//tools:gen", "//tools/exp:x"]
    assert bazel.query("//... -//lib/...") == ["//tools:gen", "//tools/exp:x"]
    with pytest.raises(mb.BazelError, match=r"invalid package name '\.\.\.-//lib': package names may not contain '//'"):
        bazel.query("//...-//lib/...")


def test_own_module_name_is_the_main_repository() -> None:
    module = 'module(name = "greeter")\n'
    bazel = mb.Bazel(
        {
            "MODULE.bazel": module,
            "a/BUILD.bazel": 'filegroup(name = "x")\nfilegroup(name = "y", srcs = ["@greeter//a:x"])\n',
        }
    )
    assert bazel.query("@greeter//a:x") == ["//a:x"]
    assert bazel.build("//a:y").ok


def test_deps_results_are_unique() -> None:
    files = {
        "docs/BUILD.bazel": 'filegroup(name = "pages", srcs = ["intro.md"])\n'
        'filegroup(name = "all", srcs = [":pages", "intro.md"])\n',
        "docs/intro.md": "",
    }
    assert ws(files).query("deps(//docs:all)") == ["//docs:all", "//docs:intro.md", "//docs:pages"]


def test_default_main_matches_the_end_of_a_src_path() -> None:
    files = {
        "p/BUILD.bazel": PY + 'py_test(name = "counting_test", srcs = ["tests/counting_test.py"])\n'
        'py_binary(name = "amb", srcs = ["x/amb.py", "y/amb.py"])\npy_binary(name = "near", srcs = ["xnear.py"])\n',
        "p/tests/counting_test.py": "",
        "p/x/amb.py": "",
        "p/y/amb.py": "",
        "p/xnear.py": "",
    }
    bazel = ws(files)
    assert bazel.build("//p:counting_test").ok
    assert (
        "Error in fail: default main file 'amb.py' matches multiple files in srcs. Perhaps specify an explicit file "
        "with 'main' attribute? Matches were: p/x/amb.py, p/y/amb.py"
    ) in bazel.build("//p:amb").error
    assert "corresponding default 'near.py' does not appear in srcs" in bazel.build("//p:near").error


def test_python_version_needs_a_registered_toolchain() -> None:
    build = PY + 'py_binary(name = "v312", srcs = ["v.py"], main = "v.py", python_version = "3.12")\n'
    build += 'py_binary(name = "v313", srcs = ["v.py"], main = "v.py", python_version = "3.13")\n'
    build += 'py_binary(name = "v314", srcs = ["v.py"], main = "v.py", python_version = "3.14")\n'
    with_313 = MODULE + 'python = use_extension("@rules_python//python/extensions:python.bzl", "python")\n'
    with_313 += 'python.toolchain(python_version = "3.13", is_default = True)\n'
    bazel = mb.Bazel({"MODULE.bazel": with_313, "p/BUILD.bazel": build, "p/v.py": ""})
    error = bazel.build("//p:v312").error
    assert (
        "While resolving toolchains for target //p:v312: No matching toolchains found for types:\n"
        "  @@bazel_tools//tools/python:toolchain_type"
    ) in error
    assert bazel.build("//p:v313").ok
    assert not bazel.build("//p:v314").ok
    # without python.toolchain(), rules_python 2.4.6 registers only its default, Python 3.14
    default = mb.Bazel({"MODULE.bazel": MODULE, "p/BUILD.bazel": build, "p/v.py": ""})
    assert default.build("//p:v314").ok
    assert not default.build("//p:v313").ok


def test_source_file_visibility_error_mentions_exports_files() -> None:
    error = _vis('filegroup(name = "fg", srcs = ["f.txt"])\n', "//b:f.txt").error
    assert error.endswith(
        "For more info see https://bazel.build/concepts/visibility. To set the visibility of that source file "
        "target, use the exports_files() function"
    )
    assert "exports_files() function" not in _vis('filegroup(name = "lib")\n').error


def test_visibility_entries_must_name_package_groups() -> None:
    files = {
        "app/BUILD.bazel": 'filegroup(name = "w")\n',
        "v1/BUILD.bazel": 'filegroup(name = "p", visibility = ["//app"])\n',
        "v2/BUILD.bazel": 'filegroup(name = "p", visibility = ["//app/..."])\n',
        "v3/BUILD.bazel": 'filegroup(name = "p", visibility = ["//app:w"])\n',
    }
    bazel = ws(files)
    assert (
        "v1/BUILD.bazel:1:10: no such target '//app:app': target 'app' not declared in package 'app' defined by "
        "app/BUILD.bazel and referenced by '//v1:p'"
    ) in bazel.build("//v1:p").error
    loading = bazel.build("//v2:p")
    assert loading.phase == "loading"
    assert (
        "//v2:p: invalid label '//app/...' in element 0 of attribute 'visibility' of 'filegroup': invalid label "
        "'//app/...': package name cannot contain '...'"
    ) in loading.error
    assert "v3/BUILD.bazel:1:10: Label '//app:w' does not refer to a package group." in bazel.build("//v3:p").error
    assert bazel.query("deps(//v3:p)") == ["//app:w", "//v3:p"]
