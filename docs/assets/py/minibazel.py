"""minibazel: a teaching simulator for Bazel's loading and analysis phases.

It evaluates the BUILD, .bzl, and MODULE.bazel files of a small workspace held in memory, then answers the
questions the course asks of a real Bazel 9 workspace: which targets exist, what they depend on, whether the
graph is valid (labels, visibility, providers, testonly, cycles, select()), what ``bazel query`` and
``bazel cquery`` return, and which tests ``bazel test`` would run.

It never compiles or runs anything. Error messages follow Bazel 9.3's wording closely, so a learner who meets
them here recognizes them in a real build. The same file runs in the browser (Pyodide) and under CPython, where
the course's checker compares it with real Bazel.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Bazel", "BazelError", "Label", "Result", "Target", "load_workspace"]

BAZEL_VERSION = "9.3.2"


class BazelError(Exception):
    """A loading, analysis, or query error, worded like Bazel's."""


class _Fail(Exception):
    """An evaluation error inside a BUILD/.bzl/MODULE.bazel file (becomes a BazelError with location)."""


# --------------------------------------------------------------------------------------------- labels


@dataclass(frozen=True, order=True)
class Label:
    """A parsed Bazel label: ``@repo//package:name``. ``repo`` is empty for the main repository."""

    repo: str
    package: str
    name: str

    def __str__(self) -> str:
        """The canonical label text, ``@repo//pkg:name`` (no ``@`` for the main repository)."""
        prefix = f"@{self.repo}" if self.repo else ""
        return f"{prefix}//{self.package}:{self.name}"

    @property
    def is_main(self) -> bool:
        """True for a label in the main repository."""
        return not self.repo


_NAME_OK = re.compile(r"^[A-Za-z0-9!%\-@^_\"#$&'()*+,;<=>?\[\]{|}~/.]+$")


def parse_label(text: str, current_package: str = "", current_repo: str = "") -> Label:
    """Parse ``text`` relative to ``current_package``.

    Raises:
        BazelError: For syntactically invalid labels.
    """
    if not isinstance(text, str):
        raise BazelError(f"expected a label string, got {type(text).__name__}")
    original = text
    if not text:
        raise BazelError("invalid label '': empty package-relative label")
    repo = current_repo
    if text.startswith("@@"):
        text = text[1:]
    if text.startswith("@"):
        rest = text[1:]
        if "//" in rest:
            repo, text = rest.split("//", 1)
            text = "//" + text
        else:
            repo, text = rest, "//:" + rest
    if text.startswith("//"):
        body = text[2:]
        if ":" in body:
            package, name = body.split(":", 1)
        else:
            package, name = body, body.rsplit("/", 1)[-1] if body else repo
    elif text.startswith(":"):
        package, name = current_package, text[1:]
    else:
        package, name = current_package, text
    if ":" in name:
        raise BazelError(f"invalid label '{original}': target names may not contain ':'")
    if package.startswith("/") or package.endswith("/") or "//" in package or "/../" in f"/{package}/":
        raise BazelError(f"invalid label '{original}': invalid package name '{package}'")
    if not name:
        raise BazelError(f"invalid label '{original}': empty target name")
    if name.startswith("/") or name.endswith("/") or "/../" in f"/{name}/" or "/./" in f"/{name}/":
        raise BazelError(f"invalid label '{original}': invalid target name '{name}'")
    if not _NAME_OK.match(name):
        raise BazelError(f"invalid label '{original}': invalid target name '{name}'")
    return Label(repo, package, name)


# --------------------------------------------------------------------------------------- rule schemas

# attribute kinds: "label", "label_list", "output", "output_list", "string", "string_list", "bool", "int",
# "string_dict", "label_dict" (label-keyed dict), "dict" (anything)
_COMMON = {
    "name": "string",
    "visibility": "visibility",
    "tags": "string_list",
    "testonly": "bool",
    "deprecation": "string",
    "features": "string_list",
    "compatible_with": "label_list",
    "target_compatible_with": "label_list",
    "exec_compatible_with": "label_list",
    "restricted_to": "label_list",
    "toolchains": "label_list",
    "applicable_licenses": "label_list",
    "package_metadata": "label_list",
    "aspect_hints": "label_list",
    "description": "string",
}
_BINARY = {"args": "string_list", "env": "string_dict", "output_licenses": "string_list", "stamp": "int"}
_TEST = {
    **_BINARY,
    "size": "string",
    "timeout": "string",
    "flaky": "bool",
    "shard_count": "int",
    "local": "bool",
    "env_inherit": "string_list",
}
_PY = {
    "srcs": "label_list",
    "deps": "label_list",
    "data": "label_list",
    "imports": "string_list",
    "srcs_version": "string",
    "python_version": "string",
    "legacy_create_init": "int",
    "precompile": "string",
    "precompile_invalidation_mode": "string",
    "precompile_optimize_level": "int",
    "precompile_source_retention": "string",
    "pyi_srcs": "label_list",
    "pyi_deps": "label_list",
    "experimental_venvs_site_packages": "label",
    "namespace_package_files": "label_list",
}
_PY_EXE = {
    **_PY,
    **_BINARY,
    "main": "label",
    "main_module": "string",
    "interpreter_args": "string_list",
    "config_settings": "label_dict",
    "pyc_collection": "string",
    "bootstrap_impl": "string",
    "package_collisions": "string",
    "venvs_use_declare_symlink": "string",
}
_GO = {
    "srcs": "label_list",
    "deps": "label_list",
    "embed": "label_list",
    "data": "label_list",
    "importpath": "string",
    "importmap": "string",
    "importpath_aliases": "string_list",
    "embedsrcs": "label_list",
    "cgo": "bool",
    "cdeps": "label_list",
    "copts": "string_list",
    "clinkopts": "string_list",
    "gc_goopts": "string_list",
    "gc_linkopts": "string_list",
    "x_defs": "string_dict",
    "goos": "string",
    "goarch": "string",
    "pure": "string",
    "static": "string",
    "race": "string",
    "msan": "string",
    "out": "string",
    "basename": "string",
    "linkmode": "string",
}
_SH = {"srcs": "label_list", "deps": "label_list", "data": "label_list"}


@dataclass(frozen=True)
class RuleClass:
    """What the simulator knows about a rule: its attributes and the providers it needs and gives."""

    kind: str
    attrs: dict[str, str]
    provides: tuple[str, ...] = ()
    # attribute -> tuple of acceptable providers (any one satisfies); "FILES" means any file-producing target
    needs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # attribute -> allowed source extensions (for srcs-like attributes)
    exts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    test: bool = False
    executable: bool = False
    mandatory: tuple[str, ...] = ()
    macro: str = ""  # the rule set's wrapping macro, for messages


def _rc(kind: str, attrs: dict[str, str], **kw: Any) -> RuleClass:
    return RuleClass(kind, {**_COMMON, **attrs}, **kw)


_PYDEP = ("PyInfo", "CcInfo")
# The Python toolchain rules_python 2.4.6 registers when MODULE.bazel calls no python.toolchain() (verified).
_RULES_PYTHON_DEFAULT_PYTHON = "3.14"
_GO_EXTS = (".go", ".s", ".S", ".h", ".c", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".inc", ".m", ".mm", ".syso")

RULES: dict[str, RuleClass] = {
    "filegroup": _rc("filegroup", {"srcs": "label_list", "data": "label_list", "output_group": "string"}),
    "genrule": _rc(
        "genrule",
        {
            "srcs": "label_list",
            "outs": "output_list",
            "cmd": "string",
            "cmd_bash": "string",
            "cmd_bat": "string",
            "cmd_ps": "string",
            "tools": "label_list",
            "executable": "bool",
            "local": "bool",
            "message": "string",
            "output_to_bindir": "bool",
            "stamp": "int",
            "output_licenses": "string_list",
        },
        mandatory=("outs",),
    ),
    "test_suite": _rc("test_suite", {"tests": "label_list"}),
    "config_setting": _rc(
        "config_setting",
        {
            "values": "string_dict",
            "define_values": "string_dict",
            "flag_values": "label_dict",
            "constraint_values": "label_list",
        },
    ),
    "alias": _rc("alias", {"actual": "label"}, mandatory=("actual",)),
    "package_group": _rc("package_group", {"packages": "string_list", "includes": "label_list"}),
    "platform": _rc(
        "platform",
        {
            "constraint_values": "label_list",
            "parents": "label_list",
            "exec_properties": "string_dict",
            "flags": "string_list",
            "remote_execution_properties": "string",
            "required_settings": "label_list",
            "missing_toolchain_error": "string",
        },
    ),
    "constraint_setting": _rc("constraint_setting", {"default_constraint_value": "nodep_label"}),
    "constraint_value": _rc("constraint_value", {"constraint_setting": "label"}, mandatory=("constraint_setting",)),
    "py_library": _rc("py_library", _PY, provides=("PyInfo",), needs={"deps": _PYDEP}, macro="py_library"),
    "py_binary": _rc(
        "py_binary",
        _PY_EXE,
        provides=("PyInfo",),
        needs={"deps": _PYDEP},
        executable=True,
        macro="py_binary",
    ),
    "py_test": _rc(
        "py_test",
        {**_PY_EXE, **_TEST},
        provides=("PyInfo",),
        needs={"deps": _PYDEP},
        test=True,
        executable=True,
        macro="py_test",
    ),
    "go_library": _rc(
        "go_library",
        _GO,
        provides=("GoInfo",),
        needs={"deps": ("GoInfo",), "embed": ("GoInfo",)},
        exts={"srcs": _GO_EXTS},
        macro="go_library",
    ),
    "go_binary": _rc(
        "go_binary",
        {**_GO, **_BINARY},
        provides=("GoInfo",),
        needs={"deps": ("GoInfo",), "embed": ("GoInfo",)},
        exts={"srcs": _GO_EXTS},
        executable=True,
        macro="go_binary_macro",
    ),
    "go_test": _rc(
        "go_test",
        {**_GO, **_TEST, "rundir": "string"},
        provides=("GoInfo",),
        needs={"deps": ("GoInfo",), "embed": ("GoInfo",)},
        exts={"srcs": _GO_EXTS},
        test=True,
        executable=True,
        macro="go_test_macro",
    ),
    "sh_library": _rc("sh_library", _SH),
    "sh_binary": _rc("sh_binary", {**_SH, **_BINARY}, executable=True),
    "sh_test": _rc("sh_test", {**_SH, **_TEST}, test=True, executable=True),
    "write_file": _rc(
        "write_file",
        {"out": "output", "content": "string_list", "is_executable": "bool", "newline": "string"},
        mandatory=("out",),
    ),
    "copy_file": _rc(
        "copy_file",
        {"src": "label", "out": "output", "is_executable": "bool", "allow_symlink": "bool"},
        mandatory=("src", "out"),
    ),
    "diff_test": _rc(
        "diff_test",
        {**_TEST, "file1": "label", "file2": "label", "failure_message": "string"},
        test=True,
        executable=True,
        mandatory=("file1", "file2"),
    ),
    "run_binary": _rc(
        "run_binary",
        {
            "tool": "label",
            "srcs": "label_list",
            "outs": "output_list",
            "args": "string_list",
            "env": "string_dict",
            "progress_message": "string",
        },
        mandatory=("tool",),
    ),
    "build_test": _rc("build_test", {**_TEST, "targets": "label_list"}, test=True, executable=True),
    "bool_flag": _rc("bool_flag", {"build_setting_default": "bool", "scope": "string"}, provides=("BuildSettingInfo",)),
    "string_flag": _rc(
        "string_flag",
        {"build_setting_default": "string", "values": "string_list", "scope": "string"},
        provides=("BuildSettingInfo",),
    ),
    "bool_setting": _rc("bool_setting", {"build_setting_default": "bool"}, provides=("BuildSettingInfo",)),
    "string_setting": _rc(
        "string_setting", {"build_setting_default": "string", "values": "string_list"}, provides=("BuildSettingInfo",)
    ),
    "compile_pip_requirements": _rc(
        "compile_pip_requirements",
        {
            "src": "label",
            "requirements_in": "label",
            "requirements_txt": "label",
            "requirements_linux": "label",
            "requirements_darwin": "label",
            "requirements_windows": "label",
            "extra_args": "string_list",
            "extra_deps": "label_list",
            "generate_hashes": "bool",
            "py_binary": "dict",
            "py_test": "dict",
            "timeout": "string",
            "data": "label_list",
            "srcs": "label_list",
        },
    ),
}
_NATIVE_RULES = (
    "filegroup",
    "genrule",
    "test_suite",
    "config_setting",
    "alias",
    "package_group",
    "platform",
    "constraint_setting",
    "constraint_value",
)

# Files that external rule sets export: "@repo//pkg:file.bzl" -> symbols.
_RULE_SETS: dict[str, dict[str, str]] = {
    "@rules_python//python:defs.bzl": {
        "py_library": "py_library",
        "py_binary": "py_binary",
        "py_test": "py_test",
        "PyInfo": "PyInfo",
        "py_runtime": "py_runtime",
        "py_runtime_pair": "py_runtime_pair",
    },
    "@rules_python//python:py_library.bzl": {"py_library": "py_library"},
    "@rules_python//python:py_binary.bzl": {"py_binary": "py_binary"},
    "@rules_python//python:py_test.bzl": {"py_test": "py_test"},
    "@rules_python//python:pip.bzl": {"compile_pip_requirements": "compile_pip_requirements"},
    "@rules_go//go:def.bzl": {
        "go_library": "go_library",
        "go_binary": "go_binary",
        "go_test": "go_test",
        "GoInfo": "GoInfo",
    },
    "@rules_shell//shell:sh_binary.bzl": {"sh_binary": "sh_binary"},
    "@rules_shell//shell:sh_test.bzl": {"sh_test": "sh_test"},
    "@rules_shell//shell:sh_library.bzl": {"sh_library": "sh_library"},
    "@bazel_skylib//rules:write_file.bzl": {"write_file": "write_file"},
    "@bazel_skylib//rules:copy_file.bzl": {"copy_file": "copy_file"},
    "@bazel_skylib//rules:diff_test.bzl": {"diff_test": "diff_test"},
    "@bazel_skylib//rules:run_binary.bzl": {"run_binary": "run_binary"},
    "@bazel_skylib//rules:build_test.bzl": {"build_test": "build_test"},
    "@bazel_skylib//rules:common_settings.bzl": {
        "bool_flag": "bool_flag",
        "string_flag": "string_flag",
        "bool_setting": "bool_setting",
        "string_setting": "string_setting",
        "BuildSettingInfo": "BuildSettingInfo",
    },
}
# Public names that are macros around a private rule class: query prints the rule class (verified in 9.3.2).
_RULE_CLASS_NAMES = {"write_file": "_write_file", "copy_file": "_copy_file", "build_test": "_empty_test"}
# Rule-set rules that are really legacy macros: their targets get generator_function = the macro's name.
_RULE_SET_MACROS = frozenset({"py_library", "py_binary", "py_test", "write_file", "copy_file", "build_test"})
_RULE_SET_MODULE = {
    "rules_python": "rules_python",
    "rules_go": "rules_go",
    "rules_shell": "rules_shell",
    "bazel_skylib": "bazel_skylib",
}
# Well-known external targets that exist when their module is visible.
_EXTERNAL_TARGETS = {
    "platforms": {
        "os:linux": "constraint_value",
        "os:macos": "constraint_value",
        "os:osx": "constraint_value",
        "os:windows": "constraint_value",
        "os:os": "constraint_setting",
        "cpu:x86_64": "constraint_value",
        "cpu:arm64": "constraint_value",
        "cpu:aarch64": "constraint_value",
        "cpu:cpu": "constraint_setting",
        "host:host": "platform",
        ":incompatible": "constraint_value",
    },
    "bazel_tools": {"tools/python:python_bootstrap_template.txt": "source file"},
    "rules_python": {
        "python/config_settings:python_version": "string_flag",
        "python:current_py_toolchain": "current_py_toolchain",
    },
}

# ------------------------------------------------------------------------------------------ targets


@dataclass
class Target:
    """A target in the simulated graph: a rule, a source file, or a generated (output) file."""

    label: Label
    kind: str  # rule class, "source file", or "generated file"
    attrs: dict[str, Any] = field(default_factory=dict)
    location: str = ""
    generating_rule: Label | None = None
    external: bool = False
    macro: str = ""  # the symbolic macro instance that declared this target, if any
    explicit: tuple[str, ...] = ()  # attribute names written at the call, in order (for --output=build)
    stack: tuple[tuple[str, str], ...] = ()  # (location, function) of each call that declared it, outermost first

    @property
    def is_rule(self) -> bool:
        """True for rule targets."""
        return self.kind not in ("source file", "generated file")

    @property
    def rule_class(self) -> RuleClass | None:
        """The simulator's description of this rule, if it is one it knows."""
        return RULES.get(self.kind)

    @property
    def name(self) -> str:
        """The target name."""
        return self.label.name

    @property
    def tags(self) -> list[str]:
        """The target's tags (empty for files)."""
        return list(self.attrs.get("tags") or [])

    def kind_string(self) -> str:
        """The string ``kind()`` matches and ``--output=label_kind`` prints."""
        return f"{_RULE_CLASS_NAMES.get(self.kind, self.kind)} rule" if self.is_rule else self.kind

    def __str__(self) -> str:
        """The target's label."""
        return str(self.label)

    def __repr__(self) -> str:
        """``<kind label>``, for debugging."""
        return f"<{self.kind_string()} {self.label}>"


class Select:
    """A ``select()`` value: a mapping of condition labels to values, possibly concatenated with plain values."""

    def __init__(self, conditions: dict[str, Any], no_match_error: str = "", package: str = "") -> None:
        if not isinstance(conditions, dict) or not conditions:
            raise _Fail("select({}) with an empty dictionary can never resolve because it includes no conditions")
        self.parts: list[tuple[str, Any]] = [("select", dict(conditions))]
        self.no_match_error = no_match_error
        self.package = package

    def _concat(self, other: Any, left: bool) -> Select:
        out = Select.__new__(Select)
        out.no_match_error = self.no_match_error
        out.package = self.package
        mine = list(self.parts)
        theirs = other.parts if isinstance(other, Select) else [("value", other)]
        out.parts = mine + theirs if left else theirs + mine
        return out

    def __add__(self, other: Any) -> Select:
        return self._concat(other, True)

    def __radd__(self, other: Any) -> Select:
        return self._concat(other, False)

    def __or__(self, other: Any) -> Select:
        return self._concat(other, True)

    def __ror__(self, other: Any) -> Select:
        return self._concat(other, False)

    def __repr__(self) -> str:
        return " + ".join(f"select({v!r})" if k == "select" else repr(v) for k, v in self.parts)


# --------------------------------------------------------------------------------------- starlark


_BANNED_NODES: dict[type, str] = {
    ast.While: "'while' not supported, use 'for' instead",
    ast.Try: "'try' not supported, all exceptions are fatal",
    ast.Import: "'import' not supported, use 'load' instead",
    ast.ImportFrom: "'import' not supported, use 'load' instead",
    ast.ClassDef: "'class' not supported",
    ast.With: "'with' not supported",
    ast.Global: "'global' not supported",
    ast.Nonlocal: "'nonlocal' not supported",
    ast.Yield: "'yield' not supported",
    ast.YieldFrom: "'yield' not supported",
    ast.Await: "'await' not supported",
    ast.AsyncFunctionDef: "'async' not supported",
    ast.Set: "syntax error: set literals are not supported",
    ast.SetComp: "syntax error: set comprehensions are not supported",
    ast.GeneratorExp: "syntax error: generator expressions are not supported",
    ast.JoinedStr: 'syntax error: f-strings are not supported (use "%s" % x or "{}".format(x))',
    ast.Raise: "'raise' not supported, use fail() instead",
    ast.Assert: "'assert' not supported, use fail() instead",
    ast.Delete: "'del' not supported",
    ast.Starred: "syntax error: star expressions are not supported here",
}
if hasattr(ast, "Match"):
    _BANNED_NODES[ast.Match] = "'match' not supported"
if hasattr(ast, "NamedExpr"):
    _BANNED_NODES[ast.NamedExpr] = "syntax error: ':=' is not supported"


def _check_starlark(tree: ast.Module, path: str, *, build_file: bool) -> None:
    """Reject Python that is not Starlark, and statements Bazel forbids in BUILD files."""
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 1)
        col = getattr(node, "col_offset", 0) + 1
        where = f"{path}:{line}:{col}"
        for kind, message in _BANNED_NODES.items():
            if isinstance(node, kind):
                raise BazelError(f"{where}: {message}")
        if isinstance(node, ast.Compare):
            if any(isinstance(op, ast.Is | ast.IsNot) for op in node.ops):
                raise BazelError(f"{where}: 'is' not supported, use '==' instead")
            if len(node.ops) > 1:
                raise BazelError(f"{where}: Operator '<' is not associative with operator '<'. Use parens.")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            raise BazelError(f"{where}: syntax error at '**': expected newline")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult):
            raise BazelError(f"{where}: syntax error at '@'")
        if build_file:
            if isinstance(node, ast.FunctionDef | ast.Lambda):
                raise BazelError(
                    f"{where}: functions may not be defined in BUILD files. "
                    "You may move the function to a .bzl file and load it."
                )
    if build_file:
        for node in tree.body:
            where = f"{path}:{node.lineno}:{node.col_offset + 1}"
            if isinstance(node, ast.For):
                raise BazelError(
                    f"{where}: `for` statements are not allowed in BUILD files. You may inline the loop, move it "
                    "to a function definition (in a .bzl file), or as a last resort use a list comprehension."
                )
            if isinstance(node, ast.If):
                raise BazelError(
                    f"{where}: `if` statements are not allowed in BUILD files. You may move conditional logic to "
                    "a function definition (in a .bzl file), or use an `if` expression for simple cases."
                )
    else:
        for node in tree.body:
            where = f"{path}:{node.lineno}:{node.col_offset + 1}"
            if isinstance(node, ast.For):
                raise BazelError(
                    f"{where}: for loops are not allowed at the top level. "
                    "You may move it inside a function or use a comprehension, [f(x) for x in sequence]"
                )
            if isinstance(node, ast.If):
                raise BazelError(
                    f"{where}: if statements are not allowed at the top level. "
                    "You may move it inside a function or use an if expression (x if condition else y)."
                )
    # load() must be a top-level statement whose arguments are string literals.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "load":
            if not any(isinstance(s, ast.Expr) and s.value is node for s in tree.body):
                raise BazelError(
                    f"{path}:{node.lineno}:{node.col_offset + 1}: syntax error: load() must be a top-level statement"
                )
            for arg in [*node.args, *[k.value for k in node.keywords]]:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    raise BazelError(f"{path}:{node.lineno}: syntax error: load() arguments must be string literals")


_SAFE_BUILTINS = {
    "len": len,
    "str": str,
    "int": int,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "sorted": sorted,
    "reversed": lambda x: list(reversed(x)),
    "range": lambda *a: list(range(*a)),
    "enumerate": lambda x, start=0: list(enumerate(x, start)),
    "zip": lambda *a: list(zip(*a, strict=False)),
    "min": min,
    "max": max,
    "any": any,
    "all": all,
    "hasattr": hasattr,
    "getattr": getattr,
    "repr": repr,
    "type": lambda x: {str: "string", int: "int", bool: "bool", list: "list", dict: "dict", tuple: "tuple"}.get(
        type(x), type(x).__name__
    ),
    "True": True,
    "False": False,
    "None": None,
    "abs": abs,
    "hash": hash,
}


def _starlark_print(*args: Any, sep: str = " ") -> None:
    import sys

    msg = sep.join(str(a) for a in args)
    _CURRENT.prints.append(msg)
    # Bazel prints "DEBUG: <file>:<line>:<col>: <message>"; the column is that of the "(" after print
    frame: Any = sys._getframe(1)
    path, line = frame.f_code.co_filename, frame.f_lineno
    text = _CURRENT.files.get(path, "").splitlines()
    src = text[line - 1] if 0 < line <= len(text) else ""
    col = src.find("print(") + 6 if "print(" in src else 1
    _CURRENT.events.append(f"DEBUG: {path}:{line}:{col}: {msg}")


def _fail(*args: Any, attr: str | None = None, sep: str = " ") -> None:
    msg = sep.join(str(a) for a in args)
    raise _Fail(f"Error in fail: {attr + ': ' if attr else ''}{msg}")


class _Ctx:
    """Mutable state for the file being evaluated (prints go here)."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.prints: list[str] = []
        self.events: list[str] = []  # DEBUG/WARNING lines Bazel prints while loading
        self.files = files or {}
        self.macro_stack: list[tuple[str, str, str]] = []  # (macro instance name, function, location) being run
        self.package: _Package | None = None


_CURRENT = _Ctx()


class _Struct:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)

    def __repr__(self) -> str:
        return "struct(" + ", ".join(f"{k} = {v!r}" for k, v in self.__dict__.items()) + ")"


class _Exec:
    """Strips Python names so the exec'd file only sees Starlark builtins."""

    @staticmethod
    def run(source: str, path: str, env: dict[str, Any]) -> dict[str, Any]:
        code = compile(source, path, "exec")
        scope: dict[str, Any] = {"__builtins__": {}}
        scope.update(env)
        try:
            exec(code, scope)
        except _Fail:
            raise
        except BazelError:
            raise
        except NameError as exc:
            name = str(exc).split("'")[1] if "'" in str(exc) else str(exc)
            line = _tb_line(exc, path)
            hint = ""
            if name in RULES or name in ("glob", "select"):
                for file, symbols in _RULE_SETS.items():
                    if name in symbols:
                        hint = f' (load it with load("{file}", "{name}"))'
                        break
            raise _Fail(f"{path}:{line}:1: name '{name}' is not defined{hint}") from exc
        except (TypeError, ValueError, KeyError, IndexError, AttributeError, ZeroDivisionError) as exc:
            line = _tb_line(exc, path)
            raise _Fail(f"{path}:{line}: Error: {exc}") from exc
        return scope


def _tb_line(exc: BaseException, path: str) -> int:
    tb = exc.__traceback__
    line = 1
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == path:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


# ------------------------------------------------------------------------------------ symbolic macros


@dataclass
class _AttrSpec:
    kind: str  # "label", "label_list", "string", "string_list", "int", "bool", "string_dict", "label_keyed..."
    mandatory: bool = False
    default: Any = None
    configurable: bool = True


def _attr_module() -> _Struct:
    def maker(kind: str) -> Any:
        def make(
            mandatory: bool = False, default: Any = None, configurable: bool = True, doc: str = "", **_kw: Any
        ) -> _AttrSpec:
            return _AttrSpec(kind, mandatory, default, configurable)

        return make

    kinds = ("label", "label_list", "string", "string_list", "int", "bool", "string_dict", "label_keyed_string_dict")
    return _Struct(**{k: maker(k) for k in kinds}, output=maker("string"), output_list=maker("string_list"))


_ATTR_TYPES = {
    "label": (str, "string"),
    "string": (str, "string"),
    "label_list": (list, "list"),
    "string_list": (list, "list"),
    "int": (int, "int"),
    "bool": (bool, "bool"),
    "string_dict": (dict, "dict"),
    "label_keyed_string_dict": (dict, "dict"),
}


def _starlark_repr(value: Any) -> str:
    import json

    if isinstance(value, Select):
        return repr(value)
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_starlark_repr(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_starlark_repr(k)}: {_starlark_repr(v)}" for k, v in value.items()) + "}"
    return str(value)


class _Macro:
    """A symbolic macro (Bazel 8+): ``macro(implementation, attrs)`` in a .bzl file."""

    def __init__(self, ws: Workspace, implementation: Any, attrs: dict[str, _AttrSpec] | None) -> None:
        self.ws = ws
        self.implementation = implementation
        self.attrs = dict(attrs or {})
        self.name = ""  # the symbol it is exported as, filled in when its .bzl file finishes loading

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        pkg = _CURRENT.package
        build_file = pkg.build_file if pkg else ""
        where = self.ws._call_location(build_file) if pkg else ""
        if args:
            raise _Fail(f"{where}: Error: {self.name}() does not accept positional arguments")
        name = kwargs.pop("name", None)
        if not isinstance(name, str) or not name:
            raise _Fail(f"{where}: Error: missing value for mandatory attribute 'name' in '{self.name}' macro")
        visibility = kwargs.pop("visibility", None)
        values: dict[str, Any] = {}
        for attr, value in kwargs.items():
            spec = self.attrs.get(attr)
            if spec is None:
                raise _Fail(f"{where}: Error: no such attribute '{attr}' in '{self.name}' macro")
            py_type, type_name = _ATTR_TYPES.get(spec.kind, (object, "value"))
            if not isinstance(value, Select) and not isinstance(value, py_type):
                got = {str: "string", list: "list", dict: "dict", int: "int", bool: "bool"}.get(type(value), "value")
                raise _Fail(
                    f"{where}: Error: expected value of type '{type_name}' for attribute '{attr}' of "
                    f"'{self.name}', but got {_starlark_repr(value)} ({got})"
                )
            values[attr] = value
        for attr, spec in self.attrs.items():
            if attr not in values:
                if spec.mandatory:
                    raise _Fail(
                        f"{where}: Error: //{pkg.name if pkg else ''}:{name}: missing value for mandatory attribute "
                        f"'{attr}' in '{self.name}' macro"
                    )
                default = spec.default
                if default is None:
                    default = {"label_list": [], "string_list": [], "int": 0, "bool": False}.get(spec.kind)
                    default = {} if spec.kind.endswith("dict") else default
                    default = "" if spec.kind == "string" else default
                values[attr] = default
            value = values[attr]
            package = pkg.name if pkg else ""
            if spec.kind == "label" and isinstance(value, str):
                value = str(parse_label(value, package))  # a Label object in real Bazel; printed the same way
            elif spec.kind == "label_list" and isinstance(value, list):
                value = [str(parse_label(v, package)) for v in value]
            if spec.configurable and not isinstance(value, Select) and value is not None:
                value = Select({"//conditions:default": value}, package=package)  # configurable: arrives as select
            values[attr] = value
        vis = [*(visibility or []), f"//{pkg.name if pkg else ''}:__pkg__"]
        _CURRENT.macro_stack.append((name, self.name, where))
        try:
            self.implementation(name=name, visibility=vis, **values)
        finally:
            _CURRENT.macro_stack.pop()


# ------------------------------------------------------------------------------------------ module


@dataclass
class _ModuleInfo:
    name: str = ""
    version: str = ""
    deps: dict[str, str] = field(default_factory=dict)  # apparent repo name -> module name
    dev_deps: set[str] = field(default_factory=set)
    repos: dict[str, str] = field(default_factory=dict)  # apparent repo -> kind ("pip", "go_sdk", ...)
    pip_hubs: dict[str, str] = field(default_factory=dict)  # hub name -> requirements lock path
    python_versions: list[str] = field(default_factory=list)
    go_versions: list[str] = field(default_factory=list)
    registered_toolchains: list[str] = field(default_factory=list)
    hub_names: dict[str, str] = field(default_factory=dict)  # apparent hub repo -> the hub_name pip.parse gave
    warnings: list[str] = field(default_factory=list)  # printed at the top of every command's output


# Tag attributes of the module extensions the simulator knows (rules_go 0.65.0, rules_python 2.4.6 sources).
_GO_SDK_COMMON = (
    "name", "goos", "goarch", "sdks", "experiments", "urls", "patches", "patch_strip", "strip_prefix",
    "experimental_build_compiler_from_source",
)  # fmt: skip
_PIP_PARSE_ATTRS = (
    "hub_name", "python_version", "requirements_lock", "requirements_linux", "requirements_darwin",
    "requirements_windows", "requirements_by_platform", "experimental_requirement_cycles", "extra_hub_aliases",
    "use_hub_alias_dependencies", "experimental_extra_index_urls", "experimental_index_url",
    "experimental_index_url_overrides", "parallel_download", "pyproject_toml", "simpleapi_skip", "target_platforms",
    "uv_lock", "whl_modifications", "add_libdir_to_library_search_path", "download_only",
    "enable_implicit_namespace_pkgs", "environment", "envsubst", "extra_pip_args", "isolated", "pip_data_exclude",
    "python_interpreter", "python_interpreter_target", "quiet", "timeout", "auth_patterns", "netrc",
)  # fmt: skip
_TAG_ATTRS: dict[tuple[str, str], tuple[str, ...]] = {
    ("go_sdk", "download"): (*_GO_SDK_COMMON, "version"),
    ("go_sdk", "from_file"): (*_GO_SDK_COMMON, "go_mod", "go_work"),
    ("go_sdk", "host"): ("name", "version", "experiments"),
    ("go_sdk", "nogo"): ("nogo", "includes", "excludes"),
    ("go_sdk", "wrap"): ("root_file", "root_files", "version", "experiments", "goos", "goarch"),
    ("pip", "parse"): _PIP_PARSE_ATTRS,
    ("python", "toolchain"): ("configure_coverage_tool", "ignore_root_user_error", "is_default", "python_version"),
}


def _module_call_location(name: str = "") -> tuple[int, int, str]:
    """(line, column of the call's '(' , source line) of the MODULE.bazel statement being evaluated."""
    import sys

    frame: Any = sys._getframe(1)
    line = 1
    while frame is not None:
        if frame.f_code.co_filename == "MODULE.bazel":
            line = frame.f_lineno
            break
        frame = frame.f_back
    text = _MODULE_SOURCE[0].splitlines()
    src = text[line - 1] if 0 < line <= len(text) else ""
    col = src.find(name + "(") + len(name) + 1 if name and name + "(" in src else src.find("(") + 1
    return line, max(col, 1), src.strip()


_MODULE_SOURCE = [""]


class _Extension:
    def __init__(self, module: _ModuleInfo, bzl: str, name: str, location: str = "MODULE.bazel") -> None:
        self._module = module
        self._bzl = bzl
        self._name = name
        self.declared: set[str] = set()
        self._location = location

    def __getattr__(self, tag: str) -> Any:
        if tag.startswith("_"):
            raise AttributeError(tag)

        def call(**kw: Any) -> None:
            allowed = _TAG_ATTRS.get((self._name, tag))
            if allowed is not None:
                import difflib

                for attr in kw:
                    if attr not in allowed:
                        line, col, src = _module_call_location(tag)
                        close = difflib.get_close_matches(attr, allowed, n=1, cutoff=0.6)
                        hint = f" (did you mean '{close[0]}'?)" if close else ""
                        raise BazelError(
                            "ERROR: Traceback (most recent call last):\n"
                            f'\tFile "MODULE.bazel", line {line}, column {col}, in <toplevel>\n\t\t{src}\n'
                            f"Error: in '{tag}' tag, unknown attribute '{attr}' provided{hint}"
                        )
            if self._bzl.endswith("pip.bzl") and tag == "parse":
                hub = kw.get("hub_name")
                lock = kw.get("requirements_lock") or kw.get("requirements_linux") or kw.get("requirements_darwin")
                if not hub:
                    raise _Fail("pip.parse: missing mandatory attribute 'hub_name'")
                if not lock:
                    raise _Fail("pip.parse: one of 'requirements_lock' or a platform-specific lock file is required")
                self._module.pip_hubs[hub] = str(lock)
                self._module.hub_names[hub] = str(hub)
                self.declared.add(hub)
                if hub == "pypi":
                    own = self._module.name
                    self._module.warnings.append(
                        "DEBUG: /…/external/rules_python+/python/private/pypi/extension.bzl:397:26: WARNING: The "
                        f"PyPI hub name 'pypi' is reserved (module '{own}'). Please rename your hub, otherwise a "
                        f"future release will rename it to '{own}_pypi'."
                    )
            elif self._bzl.endswith("python.bzl") and tag == "toolchain":
                self._module.python_versions.append(str(kw.get("python_version", "")))
            elif self._bzl.endswith("extensions.bzl") and tag == "download" and "go" in self._bzl:
                self._module.go_versions.append(str(kw.get("version", "")))

        return call


# --------------------------------------------------------------------------------------- workspace


@dataclass
class _Package:
    name: str
    build_file: str
    targets: dict[str, Target] = field(default_factory=dict)
    default_visibility: list[str] = field(default_factory=lambda: ["//visibility:private"])
    default_testonly: bool = False
    errors: list[str] = field(default_factory=list)
    prints: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


class Workspace:
    """An evaluated in-memory workspace."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = {k.strip("/").replace("\\", "/"): v for k, v in files.items()}
        self.module = _ModuleInfo()
        self.module_error: str | None = None
        self._packages: dict[str, _Package] = {}
        self._bzl_cache: dict[str, dict[str, Any]] = {}
        self._bzl_stack: list[str] = []
        self._current_command = "build"
        if "MODULE.bazel" not in self.files:
            self.module_error = (
                "ERROR: The 'build' command is only supported from within a workspace (below a directory having a "
                "MODULE.bazel file)."
            )
        else:
            try:
                self._eval_module()
            except BazelError as exc:
                self.module_error = str(exc)
        self.package_names = self._find_packages()

    # ------------------------------------------------------------------ module

    def _eval_module(self) -> None:
        source = self.files["MODULE.bazel"]
        try:
            tree = ast.parse(source, "MODULE.bazel")
        except SyntaxError as exc:
            raise BazelError(f"ERROR: MODULE.bazel:{exc.lineno}:{exc.offset}: syntax error: {exc.msg}") from exc
        try:
            _check_starlark(tree, "MODULE.bazel", build_file=True)
        except BazelError as exc:
            raise BazelError(f"ERROR: {exc}") from exc
        mod = self.module
        seen_module = [False]
        dep_locations: dict[str, str] = {}
        _MODULE_SOURCE[0] = source

        def module(name: str = "", version: str = "", **_: Any) -> None:
            if seen_module[0]:
                raise _Fail("the module() directive can only be called once")
            if mod.deps:
                raise _Fail("if module() is called, it must be called before any other functions")
            seen_module[0] = True
            mod.name, mod.version = name, version

        def bazel_dep(
            name: str, version: str = "", repo_name: str | None = None, dev_dependency: bool = False, **_: Any
        ) -> None:
            if not version and name not in ("platforms", "bazel_skylib"):
                pass
            apparent = repo_name if repo_name is not None else name
            line, col, _src = _module_call_location("bazel_dep")
            if apparent in mod.deps:
                raise _Fail(
                    f"Error in bazel_dep: The repo name '{apparent}' cannot be defined by a bazel_dep at "
                    f"MODULE.bazel:{line}:{col} as it is already defined by a bazel_dep at {dep_locations[apparent]}"
                )
            dep_locations[apparent] = f"MODULE.bazel:{line}:{col}"
            mod.deps[apparent] = name
            if dev_dependency:
                mod.dev_deps.add(apparent)

        def use_extension(bzl: str, name: str, dev_dependency: bool = False, **_: Any) -> _Extension:
            repo = bzl[1:].split("//", 1)[0] if bzl.startswith("@") else ""
            if repo and repo not in mod.deps and repo != "bazel_tools":
                raise _Fail(
                    f"Unable to find package for @[unknown repo '{repo}' requested from @@]{bzl[len(repo) + 1 :]}: "
                    f"No repository visible as '@{repo}' from main repository."
                )
            line, col, _src = _module_call_location("use_extension")
            return _Extension(mod, bzl, name, f"MODULE.bazel:{line}:{col}")

        def use_repo(ext: _Extension, *names: str, **aliases: str) -> None:
            for alias, n in [*[(n, n) for n in names], *aliases.items()]:
                if n not in ext.declared:
                    if ext._name == "pip":
                        # the pip extension runs only when a build needs the repository; until then a wrong name
                        # simply leaves @alias invisible ("No repository visible as '@alias'")
                        continue
                    repo = ext._bzl[1:].split("//", 1)[0] if ext._bzl.startswith("@") else ""
                    module_name = mod.deps.get(repo, repo)
                    canon = f"@@{module_name}+//{ext._bzl.split('//', 1)[1]}" if repo else ext._bzl
                    raise BazelError(
                        f'ERROR: module extension {canon}%{ext._name} does not generate repository "{n}", yet it '
                        f'is imported as "{alias}" in the usage at {ext._location}'
                    )
                mod.repos[alias] = ext._name
                if n in mod.pip_hubs:
                    mod.pip_hubs[alias] = mod.pip_hubs[n]
                    mod.hub_names[alias] = n

        def register_toolchains(*labels: str, **_: Any) -> None:
            mod.registered_toolchains.extend(labels)

        def _noop(*_a: Any, **_k: Any) -> None:
            return None

        env = {
            **_SAFE_BUILTINS,
            "module": module,
            "bazel_dep": bazel_dep,
            "use_extension": use_extension,
            "use_repo": use_repo,
            "register_toolchains": register_toolchains,
            "register_execution_platforms": _noop,
            "single_version_override": _noop,
            "archive_override": _noop,
            "git_override": _noop,
            "local_path_override": _noop,
            "multiple_version_override": _noop,
            "include": _noop,
            "use_repo_rule": lambda *a, **k: _noop,
            "print": _starlark_print,
            "fail": _fail,
        }
        try:
            _Exec.run(source, "MODULE.bazel", env)
        except _Fail as exc:
            raise BazelError(f"ERROR: MODULE.bazel: {exc}") from exc
        # a pip hub's repos are visible only through use_repo
        mod.pip_hubs = {k: v for k, v in mod.pip_hubs.items() if k in mod.repos}

    def visible_repos(self) -> set[str]:
        """Repositories the main repository can see by apparent name (its own module name included)."""
        own = {self.module.name} if self.module.name else set()
        return {*self.module.deps, *self.module.repos, *own, "bazel_tools", ""}

    # ------------------------------------------------------------------ packages

    def _find_packages(self) -> list[str]:
        found: dict[str, str] = {}
        for path in self.files:
            directory, _, base = path.rpartition("/")
            if base in ("BUILD.bazel", "BUILD") and (base == "BUILD.bazel" or directory not in found):
                found[directory] = path
        self._build_files = found
        return sorted(found)

    def package_of_path(self, path: str) -> str | None:
        """The package that owns a source path: the nearest ancestor directory with a BUILD file."""
        parts = path.split("/")[:-1]
        while True:
            candidate = "/".join(parts)
            if candidate in self._build_files:
                return candidate
            if not parts:
                return None
            parts.pop()

    def has_package(self, name: str) -> bool:
        """Whether ``name`` is a package (a directory with a BUILD file)."""
        return name in self._build_files

    def package(self, name: str) -> _Package:
        """Load (once) and return a package; raises BazelError for loading errors."""
        if name not in self._build_files:
            raise BazelError(
                f"no such package '{name}': BUILD file not found in any of the following directories. "
                "Add a BUILD file to a directory to mark it as a package."
            )
        pkg = self._packages.get(name)
        if pkg is None:
            pkg = _Package(name, self._build_files[name])
            self._packages[name] = pkg
            try:
                self._eval_build(pkg)
            except BazelError as exc:
                pkg.errors.append(str(exc))
            except _Fail as exc:
                pkg.errors.append(str(exc))
        if pkg.errors:
            raise BazelError(f"error loading package '{name}': {pkg.errors[0]}")
        return pkg

    def _eval_build(self, pkg: _Package) -> None:
        path = pkg.build_file
        source = self.files[path]
        try:
            tree = ast.parse(source, path)
        except SyntaxError as exc:
            raise BazelError(f"{path}:{exc.lineno}:{exc.offset}: syntax error: {exc.msg}") from exc
        _check_starlark(tree, path, build_file=True)
        global _CURRENT
        saved = _CURRENT
        _CURRENT = _Ctx(self.files)
        _CURRENT.package = pkg
        try:
            env = self._build_env(pkg, path)
            _Exec.run(source, path, env)
        finally:
            pkg.prints.extend(_CURRENT.prints)
            pkg.events.extend(_CURRENT.events)
            _CURRENT = saved
        self._attach_source_files(pkg)
        # a rule named like one of its own outputs builds, but Bazel warns (verified wording)
        for name, rule in list(pkg.targets.items()):
            if rule.is_rule and rule.rule_class is not None:
                for attr, akind in rule.rule_class.attrs.items():
                    outs = rule.attrs.get(attr) if akind in ("output", "output_list") else None
                    outs = [outs] if isinstance(outs, str) else outs if isinstance(outs, list) else []
                    if name in outs:
                        pkg.events.append(
                            f"WARNING: {rule.location}: target '{name}' is both a rule and a file; please choose "
                            "another name for the rule"
                        )

    def _attach_source_files(self, pkg: _Package) -> None:
        """Create source-file targets for every file a rule in the package references (as Bazel does)."""
        for target in list(pkg.targets.values()):
            if not target.is_rule:
                continue
            for _attr, value in _label_values(target):
                for text in value:
                    try:
                        label = parse_label(text, pkg.name)
                    except BazelError:
                        continue
                    if label.is_main and label.package == pkg.name and label.name not in pkg.targets:
                        if self._crosses_subpackage(pkg.name, label.name):
                            path = f"{pkg.name}/{label.name}" if pkg.name else label.name
                            sub = self.package_of_path(path) or ""
                            rest = path[len(sub) + 1 :]
                            raise _Fail(
                                f"{target.location}: Label '{label}' is invalid because '{sub}' is a subpackage; "
                                f"perhaps you meant to put the colon here: '//{sub}:{rest}'?"
                            )
                        # Bazel creates an input-file target for every same-package label a rule mentions; a
                        # missing file only fails later, at execution ("missing input file"). Since Bazel 9 such
                        # files take the package's default visibility (private unless package() says otherwise).
                        pkg.targets[label.name] = Target(
                            label,
                            "source file",
                            {"visibility": list(pkg.default_visibility)},
                            location=pkg.build_file,
                        )
        # the BUILD file is itself a source-file target
        base = pkg.build_file.rsplit("/", 1)[-1]
        pkg.targets.setdefault(base, Target(Label("", pkg.name, base), "source file", location=pkg.build_file))

    def _call_location(self, build_file: str) -> str:
        """``path:line:col`` of the outermost call in the BUILD file (the column of its opening parenthesis)."""
        import sys

        frame = sys._getframe(2)
        line = 1
        while frame is not None:
            if frame.f_code.co_filename == build_file:
                line = frame.f_lineno
            frame = frame.f_back  # type: ignore[assignment]
        text = self.files.get(build_file, "").splitlines()
        col = 1
        if 0 < line <= len(text) and "(" in text[line - 1]:
            col = text[line - 1].index("(") + 1
        return f"{build_file}:{line}:{col}"

    def _call_stack(self, build_file: str) -> tuple[tuple[str, str], ...]:
        """(location, function) for each BUILD/.bzl frame of the current declaration, outermost first."""
        import sys

        frame: Any = sys._getframe(2)
        chain: list[Any] = []
        while frame is not None:
            name = frame.f_code.co_filename
            if name == build_file or (name.endswith(".bzl") and name in self.files):
                chain.append(frame)
            frame = frame.f_back
        out = []
        for f in reversed(chain):
            text = self.files.get(f.f_code.co_filename, "").splitlines()
            line = f.f_lineno
            src = text[line - 1] if 0 < line <= len(text) else ""
            col = src.index("(") + 1 if "(" in src else 1
            fn = f.f_code.co_name
            out.append((f"{f.f_code.co_filename}:{line}:{col}", "<toplevel>" if fn == "<module>" else fn))
        return tuple(out)

    def _generator(self, build_file: str, kind: str) -> tuple[str, str, str] | None:
        """(generator_name, generator_function, generator_location) for a target declared through a macro.

        Bazel records the outermost legacy macro called from the BUILD file; rule-set wrappers such as py_binary
        count as macros too. A target declared directly in the BUILD file has none.
        """
        import sys

        frame: Any = sys._getframe(2)
        chain: list[Any] = []
        while frame is not None:
            chain.append(frame)
            frame = frame.f_back
        chain.reverse()  # outermost first
        for i, f in enumerate(chain):
            if f.f_code.co_filename == build_file and i + 1 < len(chain):
                nxt = chain[i + 1]
                fn = nxt.f_code.co_name
                if nxt.f_code.co_filename.endswith(".bzl") and not fn.startswith("<"):
                    name = nxt.f_locals.get("name", "")
                    return str(name), fn, self._call_location(build_file)
        return None

    def _crosses_subpackage(self, package: str, name: str) -> bool:
        path = f"{package}/{name}" if package else name
        return self.package_of_path(path) != package

    # ------------------------------------------------------------------ environments

    def _native_functions(self, pkg: _Package, path: str) -> dict[str, Any]:
        def rule_fn(kind: str) -> Any:
            def create(*args: Any, **kwargs: Any) -> None:
                where = self._call_location(pkg.build_file)
                if args:
                    raise _Fail(f"{where}: Error in {kind}: {kind}() does not accept positional arguments")
                generator = _CURRENT.macro_stack[0] if _CURRENT.macro_stack else self._generator(pkg.build_file, kind)
                if _CURRENT.macro_stack and "visibility" not in kwargs:
                    kwargs = {**kwargs, "visibility": ["//visibility:private"]}  # private to the macro
                self._declare(pkg, kind, kwargs, where)
                target = pkg.targets.get(kwargs.get("name"))  # type: ignore[arg-type]
                if target is not None:
                    target.explicit = tuple(k for k in kwargs if k != "name")
                    target.stack = self._call_stack(pkg.build_file)
                    if _CURRENT.macro_stack:
                        target.macro = _CURRENT.macro_stack[-1][0]
                    if generator is not None:
                        gen_name, gen_fn, gen_loc = generator
                        target.attrs.setdefault("generator_name", gen_name)
                        target.attrs.setdefault("generator_function", gen_fn)
                        target.attrs.setdefault("generator_location", gen_loc)

            create.__name__ = kind
            return create

        def glob(
            include: list[str] | None = None,
            exclude: list[str] | None = None,
            exclude_directories: int = 1,
            allow_empty: bool = False,
        ) -> list[str]:
            return self._glob(pkg.name, include or [], exclude or [], allow_empty, path)

        def select(conditions: dict[str, Any], no_match_error: str = "") -> Select:
            return Select(conditions, no_match_error, pkg.name)

        def package(default_visibility: list[str] | None = None, default_testonly: bool = False, **_kw: Any) -> None:
            if pkg.targets:
                raise _Fail("package() function cannot be called after any rule is declared")
            if default_visibility is not None:
                pkg.default_visibility = list(default_visibility)
            pkg.default_testonly = default_testonly

        def exports_files(srcs: list[str], visibility: list[str] | None = None, licenses: Any = None) -> None:
            for name in srcs:
                label = parse_label(name, pkg.name)
                if label.package != pkg.name:
                    raise _Fail(f"exports_files: label '{name}' must be in the current package")
                existing = pkg.targets.get(label.name)
                if existing is not None and existing.is_rule:
                    raise _Fail(
                        f"generated file '{label.name}' in rule '{existing.name}' conflicts with existing source file"
                    )
                pkg.targets[label.name] = Target(
                    label,
                    "source file",
                    {"visibility": list(visibility) if visibility is not None else ["//visibility:public"]},
                    location=path,
                )

        def package_name() -> str:
            return pkg.name

        def repository_name() -> str:
            return "@"

        def existing_rules() -> dict[str, dict[str, Any]]:
            return {t.name: {"name": t.name, "kind": t.kind, **t.attrs} for t in pkg.targets.values() if t.is_rule}

        def existing_rule(name: str) -> dict[str, Any] | None:
            t = pkg.targets.get(name)
            return {"name": t.name, "kind": t.kind, **t.attrs} if t and t.is_rule else None

        fns: dict[str, Any] = {k: rule_fn(k) for k in _NATIVE_RULES}
        fns.update(
            glob=glob,
            select=select,
            package=package,
            exports_files=exports_files,
            package_name=package_name,
            repository_name=repository_name,
            existing_rules=existing_rules,
            existing_rule=existing_rule,
            licenses=lambda *a, **k: None,
        )
        fns["_rule_fn"] = rule_fn
        return fns

    def _build_env(self, pkg: _Package, path: str) -> dict[str, Any]:
        native = self._native_functions(pkg, path)
        env: dict[str, Any] = {**_SAFE_BUILTINS, "print": _starlark_print, "fail": _fail}
        for k in (*_NATIVE_RULES, "glob", "select", "package", "exports_files", "licenses"):
            env[k] = native[k]
        env["package_name"] = native["package_name"]
        env["struct"] = _Struct
        env["Label"] = lambda s: str(parse_label(s, pkg.name))
        env["depset"] = lambda direct=None, **k: list(direct or [])

        def load(module: str, *symbols: str, **aliases: str) -> None:
            loaded = self._load_bzl(module, pkg, path)
            frame = _caller_globals()
            for sym in symbols:
                frame[sym] = self._load_symbol(loaded, module, sym, path)
            for alias, sym in aliases.items():
                frame[alias] = self._load_symbol(loaded, module, sym, path)

        env["load"] = load
        env["native"] = _Struct(**{k: v for k, v in native.items() if not k.startswith("_")})
        return env

    def _load_symbol(self, loaded: dict[str, Any], module: str, sym: str, path: str) -> Any:
        if sym.startswith("_"):
            raise _Fail(f"{path}: symbol '{sym}' is private and cannot be imported")
        if sym not in loaded:
            raise _Fail(f"{path}: Error: file '{module}' does not contain symbol '{sym}'")
        return loaded[sym]

    def _load_bzl(self, module: str, pkg: _Package, path: str) -> dict[str, Any]:
        try:
            label = parse_label(module, pkg.name)
        except BazelError as exc:
            raise _Fail(f"{path}: {exc}") from exc
        if not label.name.endswith(".bzl"):
            raise _Fail(f"{path}: The label must reference a file with extension '.bzl'")
        if label.repo:
            if label.repo not in self.visible_repos():
                raise _Fail(
                    f"Unable to find package for @@[unknown repo '{label.repo}' requested from @@]//"
                    f"{label.package}:{label.name}: The repository '@@[unknown repo '{label.repo}' requested from "
                    f"@@]' could not be resolved: No repository visible as '@{label.repo}' from main repository."
                )
            module_name = self.module.deps.get(label.repo, label.repo)
            key = f"@{module_name}//{label.package}:{label.name}"
            if key not in _RULE_SETS:
                raise _Fail(f"{path}: cannot load '{module}': no such file in the simulator's copy of @{module_name}")
            native = self._native_functions(pkg, path)
            return {sym: native["_rule_fn"](kind) if kind in RULES else kind for sym, kind in _RULE_SETS[key].items()}
        file_path = f"{label.package}/{label.name}" if label.package else label.name
        if file_path not in self.files:
            raise _Fail(f"{path}: cannot load '{module}': no such file")
        if self.package_of_path(file_path) != label.package:
            raise _Fail(
                f"{path}: Label '{module}' is invalid because '{file_path.rsplit('/', 1)[0]}' is not a package; "
                "perhaps you meant to put the colon here"
            )
        if file_path in self._bzl_stack:
            raise _Fail(f"cycle in load graph: {' -> '.join([*self._bzl_stack, file_path])}")
        # .bzl files are evaluated once; their rules record into whichever package calls them.
        source = self.files[file_path]
        try:
            tree = ast.parse(source, file_path)
        except SyntaxError as exc:
            raise BazelError(f"{file_path}:{exc.lineno}:{exc.offset}: syntax error: {exc.msg}") from exc
        _check_starlark(tree, file_path, build_file=False)
        self._bzl_stack.append(file_path)
        try:
            env = self._bzl_env(pkg, file_path, label.package)
            scope = _Exec.run(source, file_path, env)
        finally:
            self._bzl_stack.pop()
        exported = {k: v for k, v in scope.items() if k not in env or env[k] is not v}
        for k, v in exported.items():
            if isinstance(v, _Macro) and not v.name:
                v.name = k
        return exported

    def _bzl_env(self, pkg: _Package, path: str, bzl_package: str) -> dict[str, Any]:
        native = self._native_functions(pkg, path)
        env: dict[str, Any] = {**_SAFE_BUILTINS, "print": _starlark_print, "fail": _fail}
        env["select"] = native["select"]
        env["struct"] = _Struct
        env["Label"] = lambda s: str(parse_label(s, bzl_package))
        env["depset"] = lambda direct=None, **k: list(direct or [])
        env["native"] = _Struct(**{k: v for k, v in native.items() if not k.startswith("_")})
        env["attr"] = _attr_module()
        env["macro"] = lambda implementation, attrs=None, doc="", **_kw: _Macro(self, implementation, attrs)

        def load(module: str, *symbols: str, **aliases: str) -> None:
            loaded = self._load_bzl(module, _Package(bzl_package, path), path)
            # rules loaded inside a .bzl still record into the calling package
            frame = _caller_globals()
            for name, sym in [*[(s, s) for s in symbols], *aliases.items()]:
                value = self._load_symbol(loaded, module, sym, path)
                kind = getattr(value, "__name__", "")
                frame[name] = native["_rule_fn"](kind) if kind in RULES else value

        env["load"] = load
        return env

    # ------------------------------------------------------------------ declaring targets

    def _declare(self, pkg: _Package, kind: str, kwargs: dict[str, Any], path: str) -> None:
        rc = RULES[kind]
        name = kwargs.get("name")
        if name is None:
            raise _Fail(f"{path}: Error in {kind}: {kind} rule has no 'name' attribute")
        if not isinstance(name, str) or not name:
            raise _Fail(f"{path}: Error in {kind}: invalid target name '{name}'")
        try:
            parse_label(":" + name, pkg.name)
        except BazelError as exc:
            raise _Fail(f"{path}: Error in {kind}: {exc}") from exc
        for attr in kwargs:
            if attr not in rc.attrs:
                raise _Fail(f"{path}: //{pkg.name}:{name}: no such attribute '{attr}' in '{kind}' rule")
        for attr in rc.mandatory:
            if attr not in kwargs:
                raise _Fail(
                    f"{path}: //{pkg.name}:{name}: missing value for mandatory attribute '{attr}' in '{kind}' rule"
                )
        existing = pkg.targets.get(name)
        if existing is not None:
            what = f"{existing.kind} rule" if existing.is_rule else existing.kind
            raise _Fail(f"{path}: Error in {kind}: {kind} rule '{name}' conflicts with existing {what}")
        attrs: dict[str, Any] = {}
        for attr, value in kwargs.items():
            attrs[attr] = self._coerce(kind, name, attr, rc.attrs[attr], value, pkg.name, path)
        if "visibility" not in attrs:
            # config_setting is visible to everyone unless it says otherwise (Bazel: config_setting_visibility_policy)
            attrs["visibility"] = ["//visibility:public"] if kind == "config_setting" else list(pkg.default_visibility)
        if kind in _RULE_SET_MACROS:
            # rules_python and skylib wrap these rules in a legacy macro of the same name
            attrs.setdefault("generator_name", name)
            attrs.setdefault("generator_function", kind)
            attrs.setdefault("generator_location", path)
        if "testonly" not in attrs:
            attrs["testonly"] = rc.test or pkg.default_testonly
        if rc.test:
            size = attrs.get("size")
            if size is not None and size not in ("small", "medium", "large", "enormous"):
                raise _Fail(f"{path}: In rule '{name}', size '{size}' is not a valid size.")
            timeout = attrs.get("timeout")
            if timeout is not None and timeout not in ("short", "moderate", "long", "eternal"):
                raise _Fail(f"{path}: In rule '{name}', timeout '{timeout}' is not a valid timeout.")
        label = Label("", pkg.name, name)
        target = Target(label, kind, attrs, location=path)
        pkg.targets[name] = target
        for attr, akind in rc.attrs.items():
            if akind in ("output", "output_list") and attr in attrs and not isinstance(attrs[attr], Select):
                outs = attrs[attr] if akind == "output_list" else [attrs[attr]]
                for out in outs:
                    if out in pkg.targets:
                        other = pkg.targets[out]
                        if other is target:
                            continue
                        raise _Fail(
                            f"{path}: Error in {kind}: generated file '{out}' in rule '{name}' conflicts with "
                            f"existing {other.kind_string()}"
                        )
                    pkg.targets[out] = Target(
                        Label("", pkg.name, out),
                        "generated file",
                        {"visibility": attrs["visibility"]},
                        location=path,
                        generating_rule=label,
                    )

    def _coerce(self, kind: str, name: str, attr: str, akind: str, value: Any, package: str, path: str) -> Any:
        where = f"{path}: //{package}:{name}"
        if isinstance(value, Select):
            if attr in ("name", "visibility", "outs", "out", "tags", "testonly", "size"):
                raise _Fail(f"{where}: attribute '{attr}' is not configurable")
            return value
        if value is None:
            return None
        if akind in ("label_list", "string_list", "output_list", "visibility"):
            if isinstance(value, str) or not isinstance(value, list | tuple):
                raise _Fail(
                    f"{where}: expected value of type 'list(string)' for attribute '{attr}' in '{kind}' rule, "
                    f'but got "{value}" (string)'
                    if isinstance(value, str)
                    else f"{where}: expected a list for attribute '{attr}' in '{kind}' rule"
                )
            items = list(value)
            if akind == "visibility":
                for index, item in enumerate(items):
                    pkg_part = item.split(":", 1)[0]
                    if "..." in pkg_part.split("/"):
                        raise _Fail(
                            f"{where}: invalid label '{item}' in element {index} of attribute 'visibility' of "
                            f"'{kind}': invalid label '{item}': package name cannot contain '...'"
                        )
            for index, item in enumerate(items):
                if isinstance(item, Select):
                    raise _Fail(
                        f"{where}: expected value of type 'string' for element {index} of attribute '{attr}' of "
                        f"'{kind}', but got {_select_repr(item)} (select)"
                    )
                if item is None and akind in ("label_list", "string_list"):
                    raise _Fail(
                        f"{where}: expected value of type 'string' for element {index} of attribute '{attr}' of "
                        f"'{kind}', but got None (NoneType)"
                    )
            if akind == "label_list":
                for item in items:
                    try:
                        parse_label(item, package)
                    except BazelError as exc:
                        raise _Fail(f"{where}: in {attr} attribute of {kind} rule: {exc}") from exc
                seen: set[str] = set()
                for item in items:
                    canon = str(parse_label(item, package))
                    if canon in seen:
                        raise _Fail(
                            f"{where}: Label '{canon}' is duplicated in the '{attr}' attribute of rule '{name}'"
                        )
                    seen.add(canon)
            if akind == "output_list":
                for item in items:
                    if not isinstance(item, str) or item.startswith((":", "//", "@")):
                        raise _Fail(f"{where}: in {attr} attribute: output '{item}' must be a file name, not a label")
            return items
        if akind in ("label", "output", "string", "nodep_label"):
            if not isinstance(value, str):
                raise _Fail(f"{where}: expected value of type 'string' for attribute '{attr}' in '{kind}' rule")
            if akind in ("label", "nodep_label"):
                try:
                    parse_label(value, package)
                except BazelError as exc:
                    raise _Fail(f"{where}: in {attr} attribute of {kind} rule: {exc}") from exc
            return value
        if akind == "bool":
            if isinstance(value, bool) or value in (0, 1):
                return bool(value)
            raise _Fail(f"{where}: expected value of type 'bool' for attribute '{attr}' in '{kind}' rule")
        if akind == "int":
            if isinstance(value, int):
                return value
            raise _Fail(f"{where}: expected value of type 'int' for attribute '{attr}' in '{kind}' rule")
        if akind in ("string_dict", "label_dict", "dict"):
            if not isinstance(value, dict):
                raise _Fail(f"{where}: expected value of type 'dict' for attribute '{attr}' in '{kind}' rule")
            return dict(value)
        return value

    def _glob(self, package: str, include: list[str], exclude: list[str], allow_empty: bool, path: str) -> list[str]:
        if isinstance(include, str):
            raise _Fail(f"{path}: glob(): expected a list of patterns, got a string")
        prefix = f"{package}/" if package else ""
        matched: list[str] = []
        for file in sorted(self.files):
            if not file.startswith(prefix):
                continue
            rel = file[len(prefix) :]
            if rel.rsplit("/", 1)[-1] in ("BUILD", "BUILD.bazel") and "/" in rel:
                continue
            if self.package_of_path(file) != package:
                continue  # globs never cross into a subpackage
            if any(_glob_match(p, rel) for p in include) and not any(_glob_match(p, rel) for p in exclude):
                matched.append(rel)
        if not matched and not allow_empty:
            raise _Fail(
                f"{path}: Error in glob: glob pattern {include!r} didn't match anything, but allow_empty is set to "
                "False (the default value of allow_empty can be set with --incompatible_disallow_empty_glob)."
            )
        return matched

    # ------------------------------------------------------------------ lookup

    def target(self, label: Label | str) -> Target:
        """Return the target for ``label`` or raise BazelError like Bazel does."""
        if isinstance(label, str):
            label = parse_label(label)
        if label.repo and label.repo == self.module.name and label.repo not in self.module.deps:
            label = Label("", label.package, label.name)  # @<own module name>//pkg:x is the main repository
        if label.repo:
            return self._external_target(label)
        pkg = self.package(label.package)
        if label.name in pkg.targets:
            return pkg.targets[label.name]
        # A file on disk is a target only when a rule in its package mentions it or exports_files() lists it.
        hint = ""
        full = f"{label.package}/{label.name}" if label.package else label.name
        if full in self.files:
            hint = (
                f"; however, a source file of this name exists.  (Perhaps add "
                f"'exports_files([\"{label.name}\"])' to {pkg.build_file}?)"
            )
        raise BazelError(
            f"no such target '{label}': target '{label.name}' not declared in package '{label.package}' "
            f"defined by {pkg.build_file}{hint}"
        )

    def _external_target(self, label: Label) -> Target:
        if label.repo not in self.visible_repos():
            raise BazelError(
                f"no such package '@@[unknown repo '{label.repo}' requested from @@]//{label.package}': "
                f"The repository '@@[unknown repo '{label.repo}' requested from @@]' could not be resolved: "
                f"No repository visible as '@{label.repo}' from main repository"
            )
        if label.repo in self.module.pip_hubs:
            available = self.pip_packages(label.repo)
            if label.package not in available:  # labels must use the normalized name exactly
                hub = f"@@rules_python++pip+{self.module.hub_names.get(label.repo, label.repo)}"
                raise BazelError(
                    f"no such package '{hub}//{label.package}': BUILD file not found in directory "
                    f"'{label.package}' of external repository {hub}. Add a BUILD file to a directory to mark it "
                    "as a package."
                )
            if label.name not in (label.package, *_PIP_HUB_TARGETS):
                raise BazelError(
                    f"no such target '{label}': target '{label.name}' not declared in package '{label.package}'"
                )
            kind = "py_library" if label.name in (label.package, "pkg") else "filegroup"
            return Target(label, kind, {"visibility": ["//visibility:public"]}, external=True)
        module_name = self.module.deps.get(label.repo, label.repo)
        known = _EXTERNAL_TARGETS.get(module_name, {})
        key = f"{label.package}:{label.name}"
        if key in known:
            kind = known[key]
            return Target(label, kind, {"visibility": ["//visibility:public"]}, external=True)
        if label.name.endswith(".bzl"):
            return Target(label, "source file", {"visibility": ["//visibility:public"]}, external=True)
        # Unknown external target: trust it (the simulator does not model every rule set's contents).
        return Target(label, "external target", {"visibility": ["//visibility:public"]}, external=True)

    def pip_packages(self, hub: str) -> set[str]:
        """Normalized distribution names pinned in a pip hub's lock file."""
        lock = self.module.pip_hubs.get(hub, "")
        try:
            path = parse_label(lock)
        except BazelError:
            return set()
        text = self.files.get(f"{path.package}/{path.name}" if path.package else path.name, "")
        names = set()
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "--")):
                continue
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            if m:
                names.add(_normalize_dist(m.group(1)))
        return names

    def all_targets(self, package: str) -> list[Target]:
        """Every target (rules and files) in a loaded package."""
        return list(self.package(package).targets.values())


# What each package of a pip hub declares besides <name> itself (rules_python 2.4.6, `bazel query @pypi//pytest:all`).
_PIP_HUB_TARGETS = (
    "_no_matching_repository",
    "data",
    "dist_info",
    "extracted_whl_files",
    "pkg",
    "srcs",
    "whl",
    "whl_file",
)


def _caller_globals() -> dict[str, Any]:
    import sys

    frame = sys._getframe(2)
    return frame.f_globals


def _normalize_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _glob_match(pattern: str, path: str) -> bool:
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return re.fullmatch(regex, path) is not None


def _label_values(target: Target) -> list[tuple[str, list[str]]]:
    """(attribute, label strings) for every label-typed attribute, both branches of each select()."""
    rc = target.rule_class
    out: list[tuple[str, list[str]]] = []
    if rc is None:
        return out
    for attr, akind in rc.attrs.items():
        if akind not in ("label", "label_list", "label_dict") or attr not in target.attrs:
            continue
        value = target.attrs[attr]
        if value is None:
            continue
        labels: list[str] = []
        for branch in _all_branches(value):
            if akind == "label":
                labels.append(branch)
            elif akind == "label_dict":
                labels.extend(branch.keys())
            else:
                labels.extend(branch)
        out.append((attr, labels))
    return out


def _condition_labels(target: Target) -> list[Label]:
    """The select() condition keys of every attribute: Bazel makes each one a dependency (query shows them)."""
    out: list[Label] = []
    for value in target.attrs.values():
        if isinstance(value, Select):
            for kind, part in value.parts:
                if kind == "select":
                    out.extend(parse_label(k, value.package) for k in part if k != "//conditions:default")
    return out


def _all_branches(value: Any) -> list[Any]:
    """Every concrete value a (possibly select()-ed) attribute could take: each branch and each plain part."""
    if not isinstance(value, Select):
        return [value]
    flat: list[Any] = []
    for kind, part in value.parts:
        if kind == "select":
            flat.extend(part.values())
        else:
            flat.append(part)
    return [v for v in flat if v is not None]


# ------------------------------------------------------------------------------------ configuration


@dataclass
class Config:
    """The parts of a build configuration that select() can see."""

    compilation_mode: str = "fastbuild"
    defines: dict[str, str] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)  # build setting label -> value
    platform: str = "@platforms//host"
    host_os: str = "linux"
    host_cpu: str = "x86_64"
    test_tag_filters: list[str] = field(default_factory=list)
    test_size_filters: list[str] = field(default_factory=list)
    build_tests_only: bool = False
    keep_going: bool = False
    values: dict[str, str] = field(default_factory=dict)

    def is_default(self) -> bool:
        """True for the configuration of a plain ``bazel build`` on the host (no options that change outputs)."""
        return (
            self.compilation_mode == "fastbuild"
            and not self.defines
            and not self.flags
            and self.platform in ("@platforms//host", "@platforms//host:host", "@@platforms//host:host")
            and self.host_os == "linux"
        )

    @classmethod
    def parse(cls, args: list[str], ws: Workspace | None = None) -> tuple[Config, list[str]]:
        """Split command-line arguments into a Config and the remaining (non-flag) arguments."""
        cfg = cls()
        rest: list[str] = []
        i = 0
        args = list(args)
        if ws is not None:
            args = _expand_bazelrc(ws, args)
        while i < len(args):
            a = args[i]
            if a == "--":
                # everything after "--" is a target pattern (negative patterns such as -//x/... are allowed only here)
                rest.extend(["--", *args[i + 1 :]])
                break

            def take(a: str = a) -> str:
                nonlocal i
                if "=" in a:
                    return a.split("=", 1)[1]
                i += 1
                if i >= len(args):
                    raise BazelError(f"While parsing option {a}: Expected value after {a}")
                return args[i]

            if a in ("-c",) or a.startswith("--compilation_mode"):
                cfg.compilation_mode = take()
                if cfg.compilation_mode not in ("fastbuild", "dbg", "opt"):
                    spelled = (
                        f"-c {cfg.compilation_mode}" if a == "-c" else f"--compilation_mode={cfg.compilation_mode}"
                    )
                    raise BazelError(
                        f"While parsing option {spelled}: Not a valid compilation mode: '{cfg.compilation_mode}' "
                        "(should be fastbuild, dbg or opt)"
                    )
                cfg.values["compilation_mode"] = cfg.compilation_mode
            elif a.startswith("--define"):
                k, _, v = take().partition("=")
                cfg.defines[k] = v
            elif a.startswith("--platforms"):
                cfg.platform = take()
            elif a.startswith("--host_os"):
                cfg.host_os = take()
            elif a.startswith("--test_tag_filters"):
                cfg.test_tag_filters = [t for t in take().split(",") if t]
            elif a.startswith("--test_size_filters"):
                cfg.test_size_filters = [t for t in take().split(",") if t]
            elif a in ("--build_tests_only",):
                cfg.build_tests_only = True
            elif a in ("--keep_going", "-k"):
                cfg.keep_going = True
            elif a.startswith("--//") or a.startswith("--@"):
                body = a[2:]
                key, eq, val = body.partition("=")
                kind, canon = _build_setting(ws, key)
                if not eq:
                    if kind not in ("bool_flag", "bool_setting"):
                        if i + 1 >= len(args) or args[i + 1].startswith("-"):
                            raise BazelError(f"{a} :: Expected value after {a}")
                        i += 1
                        val = args[i]
                    else:
                        val = "true"
                cfg.flags[canon] = _flag_value(kind, key, val)
            elif a.startswith("--no//") or a.startswith("--no@"):
                kind, canon = _build_setting(ws, a[4:])
                if kind not in ("bool_flag", "bool_setting", ""):
                    raise BazelError(f"{a[4:]} :: Illegal use of 'no' prefix on non-boolean option: {a[4:]}")
                cfg.flags[canon] = "false"
            elif a.startswith("-") and a[1:2] in ("/", "@", ":"):
                raise BazelError(f"Invalid options syntax: {a}")
            elif a.startswith("-"):
                name, eq, val = a.lstrip("-").partition("=")
                bare = name[2:] if name.startswith("no") and name[2:] in _BOOLEAN_OPTIONS else name
                if not a.startswith("--") or (name not in _KNOWN_OPTIONS and bare not in _BOOLEAN_OPTIONS):
                    raise BazelError(f"{a.split('=', 1)[0]} :: Unrecognized option: {a.split('=', 1)[0]}")
                if name in _VALUE_OPTION_NAMES and not eq:
                    val = take()
                    eq = "="
                cfg.values[bare] = val if eq else ("false" if bare != name else "true")
            else:
                rest.append(a)
            i += 1
        cfg.values.setdefault("compilation_mode", cfg.compilation_mode)
        return cfg, rest


def _build_setting(ws: Workspace | None, text: str) -> tuple[str, str]:
    """(rule kind, canonical label) of a ``--//pkg:flag`` option; errors like Bazel for unknown labels."""
    try:
        label = parse_label(text)
    except BazelError as exc:
        raise BazelError(f"{text} :: Error loading option {text}: {exc}") from exc
    if ws is None:
        return "", str(label)
    try:
        target = ws.target(label)
    except BazelError as exc:
        raise BazelError(f"{text} :: Error loading option {text}: {exc}") from exc
    if target.kind == "external target":
        return "", str(target.label)
    if target.kind not in ("bool_flag", "string_flag", "bool_setting", "string_setting"):
        raise BazelError(f"{text} :: Unrecognized option: {text}")
    return target.kind, str(target.label)


def _flag_value(kind: str, key: str, value: str) -> str:
    """A build setting's command-line value; bool flags accept true/false/yes/no/1/0 (any case), as Bazel does."""
    if kind in ("bool_flag", "bool_setting"):
        low = value.lower()
        if low in ("true", "yes", "1"):
            return "true"
        if low in ("false", "no", "0"):
            return "false"
        raise BazelError(f"While parsing option {key}={value}: '{value}' is not a boolean")
    return value


# Commands whose .bazelrc sections apply, in order (verified in Bazel 9.3.2: cquery reads test lines, query reads
# no build lines). A later section beats an earlier one for the same option, whatever the order in the file.
_RC_INHERITANCE = {
    "build": ("common", "build"),
    "run": ("common", "build", "run"),
    "test": ("common", "build", "test"),
    "cquery": ("common", "build", "test", "cquery"),
    "query": ("common", "query"),
}


# Options the simulator accepts and ignores beyond recording them for config_setting(values = ...). Anything else
# is rejected the way Bazel rejects it: "ERROR: --name :: Unrecognized option: --name".
_VALUE_OPTION_NAMES = frozenset(
    {
        "output",
        "test_output",
        "test_arg",
        "test_env",
        "action_env",
        "disk_cache",
        "remote_cache",
        "run_under",
        "jobs",
        "universe_scope",
        "copt",
        "cpu",
        "host_platform",
        "extra_toolchains",
        "test_timeout",
        "runs_per_test",
        "flaky_test_attempts",
        "color",
        "curses",
        "repo_env",
        "stamp",
        "target_pattern_file",
        "query_file",
        "test_filter",
        "test_sharding_strategy",
        "python_version",
    }
)
_BOOLEAN_OPTIONS = frozenset(
    {
        "keep_going",
        "build_tests_only",
        "nobuild",
        "build",
        "implicit_deps",
        "tool_deps",
        "infer_universe_scope",
        "verbose_failures",
        "subcommands",
        "sandbox_debug",
        "announce_rc",
        "check_up_to_date",
        "cache_test_results",
        "test_verbose_timeout_warnings",
        "toolchain_resolution_debug",
        "show_progress",
        "experimental_ui_debug_all_events",
        "incompatible_default_to_explicit_init_py",
        "stamp",
        "enable_bzlmod",
        "incompatible_strict_action_env",
        "remote_upload_local_results",
        "order_output",
    }
)
_KNOWN_OPTIONS = _VALUE_OPTION_NAMES | _BOOLEAN_OPTIONS


def _expand_bazelrc(ws: Workspace, args: list[str]) -> list[str]:
    """Apply ``.bazelrc`` lines for build/test/query/common and expand ``--config=name``."""
    rc = ws.files.get(".bazelrc", "")
    lines: dict[str, list[str]] = {}
    for raw in rc.splitlines():
        raw = raw.split("#", 1)[0].strip()
        if not raw:
            continue
        cmd, *opts = raw.split()
        lines.setdefault(cmd, []).extend(opts)
    sections = _RC_INHERITANCE.get(ws._current_command, ("common",))
    out: list[str] = []

    def expand(items: list[str], depth: int) -> None:
        i = 0
        while i < len(items):
            a = items[i]
            if a == "--config" and i + 1 < len(items):
                i += 1
                a = "--config=" + items[i]
            if a.startswith("--config="):
                name = a.split("=", 1)[1]
                if depth > 10:
                    raise BazelError(f"Config expansion has a cycle: config value {name} expands to itself.")
                found = False
                # --config=name expands in place, section by section in inheritance order
                for section in sections:
                    if f"{section}:{name}" in lines:
                        expand(lines[f"{section}:{name}"], depth + 1)
                        found = True
                if not found:
                    raise BazelError(f"Config value '{name}' is not defined in any .rc file")
            else:
                out.append(a)
            i += 1

    for section in sections:
        expand(lines.get(section, []), 0)
    expand(list(args), 0)
    return out


# ------------------------------------------------------------------------------------------ analysis


class _Analyzer:
    """Resolves select(), then checks a target and its transitive deps the way Bazel's analysis phase does."""

    def __init__(self, ws: Workspace, cfg: Config) -> None:
        self.ws = ws
        self.cfg = cfg
        self.errors: list[str] = []
        self.done: set[Label] = set()
        self.stack: list[Label] = []
        self.missing_inputs: list[str] = []
        self._incompatible: dict[Label, list[tuple[Label, str]] | None] = {}
        self._platform_cache: set[str] | None = None

    def resolve(self, target: Target, attr: str) -> Any:
        """The attribute value in this configuration."""
        value = target.attrs.get(attr)
        if not isinstance(value, Select):
            return value
        result: Any = None
        for kind, part in value.parts:
            if kind == "select":
                chosen = self._choose(target, attr, part, value.no_match_error, value.package)
            else:
                chosen = part
            if result is None:
                result = chosen
            elif isinstance(result, list):
                result = result + list(chosen or [])
            elif isinstance(result, dict):
                result = {**result, **(chosen or {})}
            else:
                result = chosen
        return result

    def _choose(self, target: Target, attr: str, conditions: dict[str, Any], no_match: str, package: str) -> Any:
        matching: list[tuple[Label, Target]] = []
        for key in conditions:
            if key == "//conditions:default":
                continue
            label = parse_label(key, package)
            try:
                cond = self.ws.target(label)
            except BazelError as exc:
                raise BazelError(f"in {attr} attribute of {target.kind} rule {target.label}: {exc}") from exc
            if cond.kind not in ("config_setting", "constraint_value") and not cond.external:
                raise BazelError(
                    f"in {attr} attribute of {target.kind} rule {target.label}: '{label}' does not have mandatory "
                    "providers: 'ConfigMatchingProvider'"
                )
            try:
                hit = self._matches(cond)
            except BazelError as exc:
                if "in string_flag rule" not in str(exc):
                    raise
                raise BazelError(
                    f"{exc}\nERROR: {target.location}: errors encountered resolving select() keys for {target.label}"
                ) from exc
            if hit:
                matching.append((label, cond))
        if not matching:
            if "//conditions:default" in conditions:
                return conditions["//conditions:default"]
            keys = "\n".join(f" {parse_label(k, package)}" for k in conditions)
            head = f'configurable attribute "{attr}" in {target.label} doesn\'t match this configuration'
            msg = (
                f"{head}: {no_match}"
                if no_match
                else f"{head}. Would a default condition help?\n\nConditions checked:\n{keys}\n\n"
                "To see a condition's definition, run: bazel query --output=build <condition label>."
            )
            raise BazelError(f"{target.location}: {msg}")
        if len(matching) > 1:
            specialized = [m for m in matching if all(self._refines(m[1], o[1]) for o in matching if o is not m)]
            if len(specialized) != 1:
                names = "\n".join(sorted(str(m[0]) for m in matching))
                raise BazelError(
                    f"{target.location}: Illegal ambiguous match on configurable attribute "
                    f'"{attr}" in {target.label}:\n{names}\nMultiple matches are not allowed unless one is '
                    "unambiguously more specialized or they resolve to the same value. "
                    "See https://bazel.build/reference/be/functions#select."
                )
            matching = specialized
        original = next(
            k for k in conditions if k != "//conditions:default" and parse_label(k, package) == matching[0][0]
        )
        return conditions[original]

    def _settings(self, cond: Target) -> set[tuple[str, str]]:
        out: set[tuple[str, str]] = set()
        for k, v in (cond.attrs.get("values") or {}).items():
            out.add(("values", f"{k}={v}"))
        for k, v in (cond.attrs.get("define_values") or {}).items():
            out.add(("define", f"{k}={v}"))
        for k, v in (cond.attrs.get("flag_values") or {}).items():
            # keys are labels: ":env" and "//config:env" in package config are the same setting
            out.add(("flag", f"{parse_label(k, cond.label.package)}={str(v).lower()}"))
        for c in cond.attrs.get("constraint_values") or []:
            out.add(("constraint", str(parse_label(c, cond.label.package))))
        return out

    def _refines(self, a: Target, b: Target) -> bool:
        sa, sb = self._settings(a), self._settings(b)
        return sb < sa

    def platform_constraints(self) -> set[str]:
        """Constraint values of the target platform."""
        if self.cfg.platform in ("@platforms//host", "@platforms//host:host", "@@platforms//host:host"):
            os_name = {"darwin": "macos", "mac": "macos", "osx": "macos"}.get(self.cfg.host_os, self.cfg.host_os)
            return {f"@platforms//os:{os_name}", f"@platforms//cpu:{self.cfg.host_cpu}"}
        label = parse_label(self.cfg.platform)
        plat = self.ws.target(label)
        if plat.kind != "platform":
            raise BazelError(f"Target {label} was referenced as a platform, but does not provide PlatformInfo")
        constraints: set[str] = set()
        for parent in plat.attrs.get("parents") or []:
            saved = self.cfg.platform
            self.cfg.platform = str(parse_label(parent, label.package))
            constraints |= self.platform_constraints()
            self.cfg.platform = saved
        for c in plat.attrs.get("constraint_values") or []:
            constraints.add(str(parse_label(c, label.package)))
        return constraints

    def has_constraint(self, value: str) -> bool:
        """Whether the target platform has constraint ``value`` (a canonical label), counting setting defaults."""
        if value in ("@platforms//:incompatible",):
            return False
        if self._platform_cache is None:
            self._platform_cache = self.platform_constraints()
        have = self._platform_cache
        if value in have:
            return True
        # a constraint_setting's default_constraint_value applies when the platform sets no value for it
        try:
            cv = self.ws.target(value)
        except BazelError:
            return False
        if cv.kind != "constraint_value" or cv.external:
            return False
        setting_text = cv.attrs.get("constraint_setting")
        if not setting_text:
            return False
        setting_label = parse_label(setting_text, cv.label.package)
        try:
            setting = self.ws.target(setting_label)
        except BazelError:
            return False
        default = setting.attrs.get("default_constraint_value")
        if not default or parse_label(default, setting_label.package) != cv.label:
            return False
        for other in have:
            try:
                t = self.ws.target(other)
            except BazelError:
                continue
            if t.kind == "constraint_value" and not t.external:
                s2 = t.attrs.get("constraint_setting")
                if s2 and parse_label(s2, t.label.package) == setting_label:
                    return False
        return True

    def platform_label(self) -> str:
        """The target platform as real Bazel prints it in messages (canonical, ``@@`` for other repositories)."""
        if self.cfg.platform in ("@platforms//host", "@platforms//host:host", "@@platforms//host:host"):
            return "@@platforms//host:host"
        return _canonical(parse_label(self.cfg.platform))

    def config_id(self, target: Target, length: int = 6) -> str:
        """A short configuration id: real Bazel's for the default host configuration, a stable stand-in otherwise."""
        test = bool(target.rule_class and target.rule_class.test)
        if self.cfg.is_default():
            return ("e722a217" if test else "a7a71fd8")[:length]
        import hashlib

        key = repr(sorted(self.cfg.values.items())) + repr(sorted(self.cfg.flags.items())) + self.cfg.platform
        key += repr(sorted(self.cfg.defines.items())) + ("test" if test else "")
        return hashlib.sha256(key.encode()).hexdigest()[:length]

    def incompatible(self, label: Label) -> list[tuple[Label, str]] | None:
        """The dependency chain that makes ``label`` incompatible with the target platform, or None.

        Each entry is (label, reason); only the last has a reason (the constraint that was not met).
        """
        if label in self._incompatible:
            return self._incompatible[label]
        self._incompatible[label] = None  # cycles are reported elsewhere
        result: list[tuple[Label, str]] | None = None
        try:
            target = self.ws.target(label)
        except BazelError:
            return None
        if target.kind == "generated file" and target.generating_rule is not None:
            result = self.incompatible(target.generating_rule)
        elif target.is_rule and target.rule_class is not None:
            try:
                wanted = self.resolve(target, "target_compatible_with") or []
            except BazelError:
                wanted = []
            for c in wanted:
                canon = parse_label(c, label.package)
                if not self.has_constraint(str(canon)):
                    reason = f"target platform ({self.platform_label()}) didn't satisfy constraint {_canonical(canon)}"
                    result = [(label, reason)]
                    break
            if result is None:
                try:
                    edges = self.edges(target)
                except BazelError:
                    edges = []
                for attr, dep in edges:
                    if attr == "$config_conditions":
                        continue
                    chain = self.incompatible(dep)
                    if chain:
                        result = [(label, ""), *chain]
                        break
        self._incompatible[label] = result
        return result

    def incompatible_message(self, label: Label) -> str:
        """Bazel's error for an explicitly requested incompatible target."""
        chain = self.incompatible(label) or []
        lines = []
        for lbl, reason in chain:
            line = f"    {lbl} ({self.config_id(self.ws.target(lbl), 6)})"
            lines.append(f"{line}   <-- {reason}" if reason else line)
        return (
            f"Analysis of target '{label}' failed; build aborted: Target {label} is incompatible and cannot be "
            "built, but was explicitly requested.\nDependency chain:\n" + "\n".join(lines)
        )

    def _matches(self, cond: Target) -> bool:
        if cond.kind == "constraint_value" or (cond.external and cond.kind == "constraint_value"):
            return self.has_constraint(str(cond.label))
        pkg = cond.label.package
        for k, v in (cond.attrs.get("values") or {}).items():
            have = self.cfg.values.get(k)
            if k in ("compilation_mode",):
                have = self.cfg.compilation_mode
            if k == "define":
                dk, _, dv = v.partition("=")
                if self.cfg.defines.get(dk) != dv:
                    return False
                continue
            if have != v:
                return False
        for k, v in (cond.attrs.get("define_values") or {}).items():
            if self.cfg.defines.get(k) != v:
                return False
        for k, v in (cond.attrs.get("flag_values") or {}).items():
            flag_label = parse_label(k, pkg)
            setting = self.ws.target(flag_label)
            self._check_flag_value(setting)
            current = self.cfg.flags.get(str(setting.label))
            if current is None:
                default = setting.attrs.get("build_setting_default")
                current = (
                    ("true" if default else "false") if isinstance(default, bool) else str(default if default else "")
                )
                if flag_label.repo == "rules_python" and flag_label.name == "python_version":
                    current = self.ws.module.python_versions[0] if self.ws.module.python_versions else ""
            if str(current).lower() != str(v).lower():
                return False
        for c in cond.attrs.get("constraint_values") or []:
            if not self.has_constraint(str(parse_label(c, pkg))):
                return False
        return True

    def _check_flag_value(self, setting: Target) -> None:
        """bazel_skylib's string_flag fails analysis for a value outside ``values`` (verified wording)."""
        allowed = setting.attrs.get("values")
        value = self.cfg.flags.get(str(setting.label))
        if setting.kind != "string_flag" or not allowed or value is None or value in allowed:
            return
        shown = "[" + ", ".join(f'"{v}"' for v in allowed) + "]"
        raise BazelError(
            f"{setting.location}: in string_flag rule {setting.label}: \nTraceback (most recent call last):\n"
            '\tFile "/…/external/bazel_skylib+/rules/common_settings.bzl", line 157, column 13, in _string_impl\n'
            '\t\tfail("Error setting " + _no_at_str(ctx.label) + ": invalid value \'" + value + "\'. Allowed '
            'values are " + str(allowed_values))\n'
            f"Error in fail: Error setting {setting.label}: invalid value '{value}'. Allowed values are {shown}"
        )

    # ---------------------------------------------------------------- dependency edges

    def edges(self, target: Target) -> list[tuple[str, Label]]:
        """(attribute, label) for every configured dependency of a target."""
        out: list[tuple[str, Label]] = []
        if target.kind == "generated file" and target.generating_rule is not None:
            return [("generating_rule", target.generating_rule)]
        rc = target.rule_class
        if rc is None:
            return out
        for attr, akind in rc.attrs.items():
            if akind not in ("label", "label_list", "label_dict") or attr not in target.attrs:
                continue
            value = self.resolve(target, attr)
            if value is None:
                continue
            items = [value] if akind == "label" else list(value.keys()) if akind == "label_dict" else list(value)
            for item in items:
                out.append((attr, parse_label(item, target.label.package)))
        out.extend(("$config_conditions", c) for c in _condition_labels(target))
        if target.kind == "test_suite" and not target.attrs.get("tests"):
            for t in self.ws.all_targets(target.label.package):
                if t.rule_class is not None and t.rule_class.test and "manual" not in t.tags:
                    out.append(("$implicit_tests", t.label))
        return out

    # ---------------------------------------------------------------- checks

    def check(self, label: Label) -> None:
        """Analyze ``label`` and everything it depends on, recording errors."""
        if label in self.done:
            return
        if label in self.stack:
            start = self.stack.index(label)
            cycle = self.stack[start:]
            lines = [f".-> {cycle[0]}", *[f"|   {lbl}" for lbl in cycle[1:]], f"`-- {cycle[0]}"]
            first = self.ws.target(cycle[0])
            self.errors.append(
                f"{first.location}: in {first.kind} rule {cycle[0]}: cycle in dependency graph:\n" + "\n".join(lines)
            )
            return
        try:
            target = self.ws.target(label)
        except BazelError as exc:
            self.errors.append(str(exc))
            self.done.add(label)
            return
        self.stack.append(label)
        try:
            self._check_target(target)
        finally:
            self.stack.pop()
        self.done.add(label)

    def _check_target(self, target: Target) -> None:
        if target.kind == "generated file" and target.generating_rule is not None:
            self.check(target.generating_rule)
            return
        rc = target.rule_class
        if rc is None:
            return
        if target.macro and not _macro_name_ok(target.name, target.macro):
            self.errors.append(
                f"{target.location}: in {target.kind} rule {target.label}: Target {target.label} declared in symbolic "
                f"macro '{target.macro}' violates macro naming rules and cannot be built. Name must be the same as "
                "the macro's name, or the macro's name followed by '_' (recommended), '-', or '.', and a non-empty "
                "string."
            )
            return
        try:
            edges = self.edges(target)
        except BazelError as exc:
            self.errors.append(str(exc))
            return
        where = f"{target.location}"
        for attr, dep_label in edges:
            try:
                dep = self.ws.target(dep_label)
            except BazelError as exc:
                text = str(exc)
                if text.startswith("no such target"):
                    text += f" and referenced by '{target.label}'"
                self.errors.append(f"{where}: {text}")
                continue
            if attr == "$config_conditions":
                # select() keys are resolved separately (see _choose); Bazel does not check their visibility.
                self.check(dep_label)
                continue
            if attr not in ("$implicit_tests",) and not self.visible(dep, target):
                hint = (
                    ". To set the visibility of that source file target, use the exports_files() function"
                    if dep.kind == "source file"
                    else ""
                )
                self.errors.append(
                    f"{where}: in {target.kind} rule {target.label}: Visibility error:\n"
                    f"target '{dep.label}' is not visible from\ntarget '{target.label}'\n"
                    "Recommendation: modify the visibility declaration if you think the dependency is legitimate. "
                    f"For more info see https://bazel.build/concepts/visibility{hint}"
                )
            if (
                dep.is_rule
                and dep.attrs.get("testonly")
                and not target.attrs.get("testonly")
                and attr != "$implicit_tests"
            ):
                if target.kind != "test_suite":
                    self.errors.append(
                        f"{where}: in {target.kind} rule {target.label}: non-test target '{target.label}' depends on "
                        f"testonly target '{dep.label}' and doesn't have testonly attribute set"
                    )
            needs = rc.needs.get(attr)
            suffix = (
                f". Since this rule was created by the macro '{rc.macro}', the error might have been caused by "
                "the macro implementation"
                if rc.macro
                else ""
            )
            if needs and dep.kind == "source file" and not dep.external:
                # deps-style attributes accept no files: a same-package label that names no rule is reported
                # as a missing rule, an existing file as misplaced.
                path = f"{dep.label.package}/{dep.label.name}" if dep.label.package else dep.label.name
                problem = (
                    f"source file '{dep.label}' is misplaced here (expected no files)"
                    if path in self.ws.files
                    else f"rule '{dep.label}' does not exist"
                )
                self.errors.append(
                    f"{where}: in {attr} attribute of {target.kind} rule {target.label}: {problem}{suffix}"
                )
            elif needs and not self._provides(dep, needs):
                names = " or ".join(f"'{n}'" for n in needs)
                self.errors.append(
                    f"{where}: in {attr} attribute of {target.kind} rule {target.label}: '{dep.label}' does not "
                    f"have mandatory providers: {names}{suffix}"
                )
            exts = rc.exts.get(attr)
            if exts and not dep.is_rule and not dep.label.name.endswith(exts):
                self.errors.append(
                    f"{where}: in {attr} attribute of {target.kind} rule {target.label}: source file "
                    f"'{dep.label}' is misplaced here (expected {', '.join(exts[:6])})"
                )
            if attr == "tests" and target.kind == "test_suite" and dep.is_rule:
                drc = dep.rule_class
                if drc is not None and not drc.test and dep.kind != "test_suite":
                    self.errors.append(
                        f"{where}: in test_suite rule {target.label}: expecting a test or a test_suite rule but "
                        f"'{dep.label}' is not one"
                    )
            if dep.kind == "source file" and not dep.external:
                path = f"{dep.label.package}/{dep.label.name}" if dep.label.package else dep.label.name
                if path not in self.ws.files:
                    self.missing_inputs.append(str(dep.label))
            self.check(dep_label)
        self._check_visibility_labels(target)
        self._rule_specific(target)

    def _check_visibility_labels(self, target: Target) -> None:
        """A visibility entry other than public/private/__pkg__/__subpackages__ must name a package_group."""
        for v in target.attrs.get("visibility") or []:
            if v in ("//visibility:public", "//visibility:private"):
                continue
            label = parse_label(v, target.label.package)
            if label.name in ("__pkg__", "__subpackages__"):
                continue
            try:
                group = self.ws.target(label)
            except BazelError as exc:
                text = str(exc)
                if text.startswith("no such target"):
                    text += f" and referenced by '{target.label}'"
                self.errors.append(f"{target.location}: {text}")
                continue
            if group.kind != "package_group":
                self.errors.append(f"{target.location}: Label '{label}' does not refer to a package group.")

    def _provides(self, dep: Target, needs: tuple[str, ...]) -> bool:
        if dep.kind == "alias":
            try:
                return self._provides(self.ws.target(parse_label(dep.attrs["actual"], dep.label.package)), needs)
            except BazelError:
                return True
        if dep.kind == "external target":
            return True
        rc = dep.rule_class
        provided = rc.provides if rc else ()
        if dep.kind == "py_library" and dep.external:
            provided = ("PyInfo",)
        return any(n in provided for n in needs)

    def visible(self, dep: Target, user: Target) -> bool:
        """Bazel's visibility check: may ``user`` depend on ``dep``?"""
        owner = dep
        if dep.kind == "generated file" and dep.generating_rule is not None:
            owner = self.ws.target(dep.generating_rule)
        if owner.macro and owner.macro != user.macro and not dep.external:
            # a symbolic macro's targets are private to the macro, even within the package (verified in 9.3.2)
            vis = owner.attrs.get("visibility") or ["//visibility:private"]
            return self._allowed(vis, owner.label.package, user.label.package, set())
        if dep.external or dep.label.package == user.label.package:
            return True
        dep = owner
        if dep.kind == "source file":
            vis = dep.attrs.get("visibility")
            if vis is None:
                return False  # Bazel 9: source files are private unless exported
        else:
            vis = self.resolve(dep, "visibility") or ["//visibility:private"]
        return self._allowed(vis, dep.label.package, user.label.package, set())

    def _allowed(self, vis: list[str], owner_pkg: str, user_pkg: str, seen: set[str]) -> bool:
        for v in vis:
            if v == "//visibility:public":
                return True
            if v == "//visibility:private":
                continue
            label = parse_label(v, owner_pkg)
            if label.name == "__pkg__" and label.package == user_pkg:
                return True
            if label.name == "__subpackages__" and (
                user_pkg == label.package or user_pkg.startswith(label.package + "/") or label.package == ""
            ):
                return True
            if label.name not in ("__pkg__", "__subpackages__"):
                key = str(label)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    group = self.ws.target(label)
                except BazelError:
                    continue
                if group.kind == "package_group":
                    # A negative spec ("-//pkg/...") excludes wherever it appears in the list; a package is in the
                    # group when some positive spec matches it and no negative spec does.
                    positive = negative = False
                    for spec in group.attrs.get("packages") or []:
                        neg = spec.startswith("-")
                        body = spec.lstrip("-")
                        body = body[2:] if body.startswith("//") else body
                        hit = body in ("public", "...", user_pkg) or (
                            body.endswith("/...") and (user_pkg == body[:-4] or user_pkg.startswith(body[:-4] + "/"))
                        )
                        if hit and neg:
                            negative = True
                        elif hit:
                            positive = True
                    if positive and not negative:
                        return True
                    for inc in group.attrs.get("includes") or []:
                        if self._allowed([inc], group.label.package, user_pkg, seen):
                            return True
        return False

    def _rule_specific(self, target: Target) -> None:
        where = target.location
        if target.kind == "string_flag":
            try:
                self._check_flag_value(target)
            except BazelError as exc:
                self.errors.append(str(exc))
        if target.kind in ("py_binary", "py_test"):
            srcs = self.resolve(target, "srcs") or []
            main = self.resolve(target, "main")
            if not main and not target.attrs.get("main_module"):
                # rules_python matches the default main against the end of each src path: tests/x_test.py works.
                default = f"{target.name}.py"
                names = [parse_label(s, target.label.package).name for s in srcs]
                hits = [n for n in names if n == default or n.endswith("/" + default)]
                if not hits:
                    self.errors.append(
                        f"{where}: in {target.kind} rule {target.label}: \nError in fail: corresponding default "
                        f"'{default}' does not appear in srcs. Add it or override default file name with a 'main' "
                        "attribute"
                    )
                elif len(hits) > 1:
                    prefix = f"{target.label.package}/" if target.label.package else ""
                    self.errors.append(
                        f"{where}: in {target.kind} rule {target.label}: \nError in fail: default main file "
                        f"'{default}' matches multiple files in srcs. Perhaps specify an explicit file with 'main' "
                        f"attribute? Matches were: {', '.join(prefix + h for h in hits)}"
                    )
            elif main:
                names = [str(parse_label(s, target.label.package)) for s in srcs]
                if str(parse_label(main, target.label.package)) not in names:
                    self.errors.append(
                        f"{where}: in {target.kind} rule {target.label}: \nError in fail: could not find '{main}' as "
                        "specified by 'main' attribute"
                    )
            wanted = self.resolve(target, "python_version")
            if wanted and not self._python_registered(str(wanted)):
                self.errors.append(
                    f"{where}: While resolving toolchains for target {target.label}: No matching toolchains found "
                    "for types:\n  @@bazel_tools//tools/python:toolchain_type\nTo debug, rerun with "
                    "--toolchain_resolution_debug='@@bazel_tools//tools/python:toolchain_type'"
                )
        if target.kind == "genrule":
            self._check_make_vars(target)
        elif target.rule_class is not None and target.kind != "genrule":
            self._check_location_attrs(target)
        if target.kind in ("go_binary", "go_test", "go_library"):
            srcs = self.resolve(target, "srcs") or []
            embed = self.resolve(target, "embed") or []
            if target.kind == "go_library" and not srcs and not embed:
                pass

    def _python_registered(self, version: str) -> bool:
        """Whether a Python toolchain for ``version`` is registered.

        Registered versions come from python.toolchain() calls; without any, rules_python 2.4.6's default (3.14).
        """
        registered = [v for v in self.ws.module.python_versions if v] or [_RULES_PYTHON_DEFAULT_PYTHON]

        def minor(v: str) -> str:
            return ".".join(v.split(".")[:2])

        return any(version == v or minor(version) == v or version == minor(v) for v in registered)

    _PREREQ_ATTRS = ("srcs", "deps", "data", "tools", "tool", "embed")

    def _prerequisites(self, target: Target) -> set[str]:
        pkg = target.label.package
        out: set[str] = set()
        for attr in self._PREREQ_ATTRS:
            if target.rule_class is None or attr not in target.rule_class.attrs:
                continue
            value = self.resolve(target, attr)
            if value is None:
                continue
            for item in [value] if isinstance(value, str) else value:
                try:
                    out.add(str(parse_label(item, pkg)))
                except BazelError:
                    pass
        for attr in ("outs", "out"):
            value = target.attrs.get(attr)
            if isinstance(value, str):
                out.add(str(Label("", pkg, value)))
            elif isinstance(value, list):
                out.update(str(Label("", pkg, o)) for o in value)
        return out

    def _location_refs(self, text: str) -> list[tuple[str, str]]:
        return [
            (m.group(1), m.group(2).strip())
            for m in re.finditer(
                r"\$\((location|locations|execpath|execpaths|rootpath|rootpaths|rlocationpath|rlocationpaths)"
                r"\s+([^)]+)\)",
                text,
            )
        ]

    def _check_location_attrs(self, target: Target) -> None:
        """$(location)-style variables in ``args`` and ``env`` must name a declared prerequisite (verified wording)."""
        rc = target.rule_class
        if rc is None:
            return
        pkg = target.label.package
        texts: list[tuple[str, str]] = []
        args = self.resolve(target, "args") if "args" in rc.attrs else None
        texts.extend(("args", a) for a in args or [] if isinstance(a, str))
        env = self.resolve(target, "env") if "env" in rc.attrs else None
        texts.extend((f"env[{k}]", v) for k, v in (env or {}).items() if isinstance(v, str))
        if not texts:
            return
        prereq: set[str] | None = None
        suffix = (
            f". Since this rule was created by the macro '{rc.macro}', the error might have been caused by the "
            "macro implementation"
            if rc.macro
            else ""
        )
        for attr, text in texts:
            for _fn, ref in self._location_refs(text):
                if prereq is None:
                    prereq = self._prerequisites(target)
                try:
                    label = str(parse_label(ref, pkg))
                except BazelError as exc:
                    self.errors.append(f"{target.location}: {exc}")
                    continue
                if label not in prereq:
                    # Starlark rules (run_binary) expand with ctx.expand_location: no attribute in the message
                    where = (
                        f"in {target.kind} rule {target.label}"
                        if target.kind == "run_binary"
                        else f"in {attr} attribute of {target.kind} rule {target.label}"
                    )
                    self.errors.append(
                        f"{target.location}: {where}: label '{label}' in $(location) expression is not a declared "
                        f"prerequisite of this rule{suffix if target.kind != 'run_binary' else ''}"
                    )

    def _files_of(self, label: Label, seen: set[Label] | None = None) -> list[str]:
        """The files a label stands for in a genrule's srcs (target configuration), as execution paths."""
        seen = seen if seen is not None else set()
        if label in seen:
            return []
        seen.add(label)
        bin_dir = f"bazel-out/k8-{self.cfg.compilation_mode}/bin"
        try:
            t = self.ws.target(label)
        except BazelError:
            return []
        rel = f"{label.package}/{label.name}" if label.package else label.name
        if t.external:
            return [f"external/{label.repo}+/{rel}"]
        if t.kind == "source file":
            return [rel]
        if t.kind == "generated file":
            return [f"{bin_dir}/{rel}"]
        pkg = label.package
        prefix = f"{pkg}/" if pkg else ""
        if t.kind in ("filegroup", "py_library"):
            files: list[str] = []
            for x in self.resolve(t, "srcs") or []:
                files.extend(self._files_of(parse_label(x, pkg), seen))
            return files
        if t.kind == "genrule":
            return [f"{bin_dir}/{prefix}{o}" for o in t.attrs.get("outs") or []]
        if t.kind in ("go_binary", "go_test"):
            return [f"{bin_dir}/{prefix}{t.name}_/{t.name}"]
        if t.kind in ("py_binary", "py_test", "sh_binary", "sh_test"):
            files = [f"{bin_dir}/{prefix}{t.name}"]
            for x in self.resolve(t, "srcs") or []:
                files.extend(self._files_of(parse_label(x, pkg), seen))
            return files
        if t.kind in ("write_file", "copy_file") and t.attrs.get("out"):
            return [f"{bin_dir}/{prefix}{t.attrs['out']}"]
        return [f"{bin_dir}/{prefix}{t.name}"]

    @staticmethod
    def _bare_dollar(cmd: str) -> str:
        """Bazel's error for a shell-style $NAME or ${NAME} in a genrule command, or '' when there is none."""
        i = 0
        while i < len(cmd):
            if cmd[i] != "$":
                i += 1
                continue
            nxt = cmd[i + 1 : i + 2]
            if nxt == "":
                return "unterminated $"
            if nxt in ("$", "@", "<", "("):
                if nxt == "(":
                    end = cmd.find(")", i)
                    i = end + 1 if end >= 0 else len(cmd)
                else:
                    i += 2
                continue
            if nxt == "{":
                end = cmd.find("}", i)
                name = cmd[i + 2 : end] if end >= 0 else cmd[i + 2 :]
                return (
                    f"'${{{name}}}' syntax is not supported; use '$({name})' instead for \"Make\" variables, or "
                    "escape the '$' as '$$' if you intended this for the shell"
                )
            m = re.match(r"[A-Za-z0-9_]+", cmd[i + 1 :])
            if m:
                name = m.group(0)
                return (
                    f"'${name}' syntax is not supported; use '$({name})' instead for \"Make\" variables, or escape "
                    "the '$' as '$$' if you intended this for the shell"
                )
            i += 2
        return ""

    def _check_make_vars(self, target: Target) -> None:
        cmds = [target.attrs.get(k) for k in ("cmd", "cmd_bash")]
        cmd = next((c for c in cmds if isinstance(c, str) and c), None)
        if cmd is None:
            if not any(target.attrs.get(k) for k in ("cmd", "cmd_bash", "cmd_bat", "cmd_ps")):
                self.errors.append(f"{target.location}: in genrule rule {target.label}: missing value for 'cmd'")
            return
        pkg = target.label.package
        outs = target.attrs.get("outs") or []
        srcs = self.resolve(target, "srcs") or []
        tools = self.resolve(target, "tools") or []
        prereq = {str(parse_label(x, pkg)) for x in [*srcs, *tools]} | {str(Label("", pkg, o)) for o in outs}
        in_srcs = {str(parse_label(x, pkg)) for x in srcs} - {str(parse_label(x, pkg)) for x in tools}
        where = f"{target.location}: in cmd attribute of genrule rule {target.label}"
        bare = self._bare_dollar(cmd)
        if bare:
            self.errors.append(f"{where}: {bare}")
            return
        for fn, ref in self._location_refs(cmd):
            try:
                label = str(parse_label(ref, pkg))
            except BazelError as exc:
                self.errors.append(f"{where}: {exc}")
                continue
            if label not in prereq:
                self.errors.append(
                    f"{where}: label '{label}' in $(location) expression is not a declared prerequisite of this rule"
                )
            elif not fn.endswith("s") and label in in_srcs:
                # a label in srcs (target configuration) stands for all its files; in tools, for its executable
                files = self._files_of(parse_label(label))
                if not files:
                    self.errors.append(f"{where}: label '{label}' in $(location) expression expands to no files")
                elif len(files) > 1:
                    self.errors.append(
                        f"{where}: label '{label}' in $(location) expression expands to more than one file, please "
                        f"use $(locations {label}) instead.  Files (at most 5 shown) are: [{', '.join(files[:5])}]"
                    )
        if "$@" in cmd and len(outs) != 1:
            self.errors.append(f"{where}: variable '$@' : more than one output file")
        if "$<" in cmd and len(srcs) != 1:
            self.errors.append(f"{where}: variable '$<' : more than one input file")
        for m in re.finditer(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", cmd):
            if m.group(1) not in (
                "SRCS",
                "OUTS",
                "RULEDIR",
                "@D",
                "GENDIR",
                "BINDIR",
                "TARGET_CPU",
                "COMPILATION_MODE",
                "PYTHON3",
            ):
                self.errors.append(f"{where}: $({m.group(1)}) not defined")


# ------------------------------------------------------------------------------------------- query


_TOKEN = re.compile(r"\s*(?:(\()|(\))|(,)|(\+|\^|-(?=[\s/@:]))|\"([^\"]*)\"|'([^']*)'|([^\s(),\"']+))")


# Functions `bazel query` accepts (Bazel 9.3.2's list; allrdeps also needs --universe_scope or
# --infer_universe_scope), and the subset the simulator evaluates.
_BAZEL_QUERY_FUNCTIONS = frozenset(
    {
        "allpaths",
        "attr",
        "buildfiles",
        "deps",
        "executables",
        "filter",
        "kind",
        "labels",
        "loadfiles",
        "rdeps",
        "same_pkg_direct_rdeps",
        "siblings",
        "some",
        "somepath",
        "tests",
        "visible",
    }
)
_QUERY_FUNCTIONS = _BAZEL_QUERY_FUNCTIONS | {"set"}


class _Query:
    """A small `bazel query` evaluator: patterns, set operations, and the common functions."""

    def __init__(
        self, ws: Workspace, analyzer: _Analyzer | None, configured: bool, universe: list[str] | None = None
    ) -> None:
        self.ws = ws
        self.an = analyzer or _Analyzer(ws, Config())
        self.configured = configured
        # --universe_scope patterns; [] means --infer_universe_scope; None means neither (allrdeps unavailable)
        self.universe = universe
        self.expr = ""

    def run(self, expr: str) -> list[Label]:
        self.expr = expr
        tokens = self._tokenize(expr)
        self.tokens = tokens
        self.pos = 0
        self.vars: dict[str, set[Label]] = {}
        self.path_order: list[Label] | None = None
        result = self._expr()
        if self.pos != len(self.tokens):
            raise BazelError(f"syntax error at '{self.tokens[self.pos][1]}'")
        if self.path_order is not None and set(self.path_order) == result:
            return list(self.path_order)  # a bare somepath() prints the path in order, start to end
        # Bazel sorts by repository, then package, then name: //tools:gen before //tools/exp:x.
        return sorted(result, key=lambda lbl: (lbl.repo != "", lbl.repo, lbl.package, lbl.name))

    def _tokenize(self, expr: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        i = 0
        expr = expr.strip()
        while i < len(expr):
            m = _TOKEN.match(expr, i)
            if not m or m.end() == i:
                raise BazelError(f"syntax error in query expression '{expr}'")
            i = m.end()
            if m.group(1):
                out.append(("(", "("))
            elif m.group(2):
                out.append((")", ")"))
            elif m.group(3):
                out.append((",", ","))
            elif m.group(4):
                out.append(("op", m.group(4)))
            elif m.group(5) is not None:
                out.append(("word", m.group(5)))
            elif m.group(6) is not None:
                out.append(("word", m.group(6)))
            elif m.group(7):
                w = m.group(7)
                if w in ("union", "intersect", "except"):
                    out.append(("op", {"union": "+", "intersect": "^", "except": "-"}[w]))
                else:
                    out.append(("word", w))
        return out

    def _peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self) -> tuple[str, str]:
        tok = self._peek()
        if tok is None:
            raise BazelError("syntax error: premature end of query expression")
        self.pos += 1
        return tok

    def _expr(self) -> set[Label]:
        left = self._primary()
        while (tok := self._peek()) is not None and tok[0] == "op":
            self.pos += 1
            self.path_order = None
            right = self._primary()
            left = left | right if tok[1] == "+" else left & right if tok[1] == "^" else left - right
        return left

    def _primary(self) -> set[Label]:
        kind, value = self._next()
        if kind == "word" and value == "let":
            name_tok = self._next()
            eq = self._next()
            if name_tok[0] != "word" or eq[1] != "=":
                raise BazelError(f"syntax error in let expression of '{self.expr}'")
            value_set = self._expr()
            if self._next()[1] != "in":
                raise BazelError(f"syntax error in let expression of '{self.expr}': expected 'in'")
            saved = self.vars.get(name_tok[1])
            self.vars[name_tok[1]] = value_set
            body = self._expr()
            if saved is None:
                self.vars.pop(name_tok[1], None)
            else:
                self.vars[name_tok[1]] = saved
            self.path_order = None
            return body
        if kind == "word" and value.startswith("$"):
            name = value[1:]
            if name not in self.vars:
                raise BazelError(
                    f'Evaluation of subquery "{value}" failed (did you want to use --keep_going?): undefined '
                    f"variable '{name}'"
                )
            return set(self.vars[name])
        if kind == "(":
            out = self._expr()
            if self._next()[0] != ")":
                raise BazelError("syntax error: expected ')'")
            return out
        if kind != "word":
            raise BazelError(f"syntax error at '{value}'")
        nxt = self._peek()
        if nxt is not None and nxt[0] == "(":
            if value not in _QUERY_FUNCTIONS and not (value == "allrdeps" and self.universe is not None):
                # Bazel's message quotes the function name, the '(' and the next token.
                after = self.tokens[self.pos + 1][1] if self.pos + 1 < len(self.tokens) else ""
                raise BazelError(
                    f"Error while parsing '{self.expr}': unknown function '{value}' at '{value} ( {after}'; "
                    f"expected one of [{', '.join(repr(f) for f in sorted(_BAZEL_QUERY_FUNCTIONS))}]"
                )
            self.pos += 1
            return self._call(value)
        return self.pattern(value)

    def _args(self) -> list[Any]:
        args: list[Any] = []
        while True:
            tok = self._peek()
            if tok is None:
                raise BazelError("syntax error: unclosed '('")
            if tok[0] == ")":
                self.pos += 1
                return args
            if tok[0] == ",":
                self.pos += 1
                continue
            args.append(self.pos)
            depth = 0
            while True:
                t = self._peek()
                if t is None:
                    break
                if t[0] == "(":
                    depth += 1
                elif t[0] == ")":
                    if depth == 0:
                        break
                    depth -= 1
                elif t[0] == "," and depth == 0:
                    break
                self.pos += 1

    def _arg_expr(self, start: int) -> set[Label]:
        saved = self.pos
        self.pos = start
        out = self._expr()
        self.pos = saved
        return out

    def _arg_word(self, start: int) -> str:
        return self.tokens[start][1]

    def _call(self, fn: str) -> set[Label]:
        if fn == "set":
            out: set[Label] = set()
            while (tok := self._next())[0] != ")":
                if tok[0] != "word":
                    raise BazelError(f"syntax error in set(): unexpected '{tok[1]}'")
                out |= self.pattern(tok[1])
            return out
        args = self._args()
        n = len(args)

        def need(lo: int, hi: int | None = None) -> None:
            if n < lo or n > (hi if hi is not None else lo):
                raise BazelError(f"syntax error: {fn}() takes {lo}{'-' + str(hi) if hi and hi != lo else ''} arguments")

        if fn == "deps":
            need(1, 2)
            depth = int(self._arg_word(args[1])) if n == 2 else None
            return self.closure(self._arg_expr(args[0]), depth, forward=True)
        if fn == "rdeps":
            need(2, 3)
            universe = self.closure(self._arg_expr(args[0]), None, forward=True)
            depth = int(self._arg_word(args[2])) if n == 3 else None
            return self.rclosure(universe, self._arg_expr(args[1]), depth)
        if fn == "allrdeps" and self.universe is not None:
            need(1, 2)
            roots = self._arg_expr(args[0])
            scope: set[Label] = set()
            for pattern in self.universe:
                scope |= self.pattern(pattern)
            universe = self.closure(scope or roots, None, forward=True)
            depth = int(self._arg_word(args[1])) if n == 2 else None
            return self.rclosure(universe, self._arg_expr(args[0]), depth)
        if fn in ("somepath", "allpaths"):
            need(2)
            src, dst = self._arg_expr(args[0]), self._arg_expr(args[1])
            found = self.paths(src, dst, all_paths=fn == "allpaths")
            if fn == "somepath":
                self.path_order = list(self._last_path)
            return found
        if fn == "kind":
            need(2)
            pat = re.compile(self._arg_word(args[0]))
            return {lbl for lbl in self._arg_expr(args[1]) if pat.search(self.ws.target(lbl).kind_string())}
        if fn == "filter":
            need(2)
            pat = re.compile(self._arg_word(args[0]))
            return {lbl for lbl in self._arg_expr(args[1]) if pat.search(str(lbl))}
        if fn == "attr":
            need(3)
            attr, pat = self._arg_word(args[0]), re.compile(self._arg_word(args[1]))
            out = set()
            for lbl in self._arg_expr(args[2]):
                t = self.ws.target(lbl)
                if attr in t.attrs or (t.rule_class and attr in t.rule_class.attrs):
                    if pat.search(_attr_string(t, attr)):
                        out.add(lbl)
            return out
        if fn == "labels":
            need(2)
            attr = self._arg_word(args[0])
            out = set()
            for lbl in self._arg_expr(args[1]):
                t = self.ws.target(lbl)
                rc = t.rule_class
                if rc is None or attr not in t.attrs:
                    continue
                akind = rc.attrs.get(attr)
                if akind in ("output", "output_list"):
                    outs = t.attrs[attr] if akind == "output_list" else [t.attrs[attr]]
                    out.update(Label("", lbl.package, o) for o in outs)
                    continue
                if akind not in ("label", "label_list", "label_dict"):
                    continue
                values = [self.an.resolve(t, attr)] if self.configured else _all_branches(t.attrs[attr])
                for value in values:
                    if value is None:
                        continue
                    items = [value] if akind == "label" else list(value)
                    out.update(parse_label(x, lbl.package) for x in items)
            return out
        if fn == "tests":
            need(1)
            return self.tests(self._arg_expr(args[0]))
        if fn == "siblings":
            need(1)
            pkgs = {lbl.package for lbl in self._arg_expr(args[0]) if lbl.is_main}
            return {t.label for p in pkgs for t in self.ws.all_targets(p)}
        if fn == "buildfiles":
            need(1)
            out = set()
            for lbl in self._arg_expr(args[0]):
                if lbl.is_main:
                    pkg = self.ws.package(lbl.package)
                    out.add(Label("", lbl.package, pkg.build_file.rsplit("/", 1)[-1]))
            return out
        if fn == "same_pkg_direct_rdeps":
            need(1)
            targets = self._arg_expr(args[0])
            out = set()
            for lbl in targets:
                for t in self.ws.all_targets(lbl.package):
                    if lbl in {d for _, d in self._edges(t)}:
                        out.add(t.label)
            return out
        raise BazelError(f"the simulator does not implement the query function '{fn}'")

    # ---------------------------------------------------------------- patterns

    def pattern(self, text: str) -> set[Label]:
        """Expand a target pattern: //..., //pkg/..., //pkg:all, //pkg:*, or a single label."""
        if not text.startswith(("//", ":", "@")) and "/" in text and text in self.ws.files and ":" not in text:
            # a workspace-relative file path names the file's target in its owning package: core/x.py -> //core:x.py
            owner = self.ws.package_of_path(text)
            if owner is not None:
                rel = text[len(owner) + 1 :] if owner else text
                return {self.ws.target(Label("", owner, rel)).label}
        if text.startswith("@"):
            repo = text.lstrip("@").split("//", 1)[0]
            body = text.split("//", 1)[1] if "//" in text else ""
            if repo in self.ws.module.pip_hubs and (body.endswith("...") or body.endswith((":all", ":*"))):
                dists = sorted(self.ws.pip_packages(repo))
                if not body.endswith("..."):
                    pkg = body.split(":", 1)[0]
                    self.ws.target(Label(repo, pkg, pkg))  # errors for a package that is not in the hub
                    dists = [pkg]
                return {Label(repo, d, n) for d in dists for n in (d, *_PIP_HUB_TARGETS)}
            return {self.ws.target(parse_label(text)).label}
        t = text
        if t.startswith(":"):
            t = "//" + t
        elif not t.startswith("//"):
            t = "//" + t
        body = t[2:]
        package_part = body.split(":", 1)[0]
        if "//" in package_part:
            raise BazelError(
                f"invalid package name '{package_part.rsplit('/', 1)[0]}': package names may not contain '//' path "
                "separators"
            )
        recursive = body == "..." or body.startswith("...:") or "/...:" in body or body.endswith("/...")
        if recursive:
            base, _, suffix = body.partition("...")
            base = base.rstrip("/")
            files = suffix in (":*", ":all-targets")
            matched = [p for p in self.ws.package_names if base == "" or p == base or p.startswith(base + "/")]
            if not matched:
                raise BazelError(f"no targets found beneath '{base}'")
            out: set[Label] = set()
            for p in matched:
                for target in self.ws.all_targets(p):
                    if files or (target.is_rule and not ("manual" in target.tags and self.skip_manual)):
                        out.add(target.label)
            return out
        if ":" in body:
            pkg, name = body.split(":", 1)
            if name in ("all", "*", "all-targets"):
                targets = self.ws.all_targets(pkg)
                if name == "all":
                    return {x.label for x in targets if x.is_rule and not ("manual" in x.tags and self.skip_manual)}
                return {x.label for x in targets}
        return {self.ws.target(parse_label(t)).label}

    skip_manual = False

    # ---------------------------------------------------------------- graph walks

    def _edges(self, target: Target) -> list[tuple[str, Label]]:
        if self.configured:
            return self.an.edges(target)
        if target.kind == "generated file" and target.generating_rule is not None:
            return [("generating_rule", target.generating_rule)]
        out = []
        for attr, values in _label_values(target):
            for v in values:
                out.append((attr, parse_label(v, target.label.package)))
        out.extend(("$config_conditions", c) for c in _condition_labels(target))
        # query also follows visibility labels that name package groups (not public/private/__pkg__/...)
        for v in target.attrs.get("visibility") or [] if target.is_rule else []:
            if v not in ("//visibility:public", "//visibility:private"):
                label = parse_label(v, target.label.package)
                if label.name not in ("__pkg__", "__subpackages__"):
                    out.append(("$visibility", label))
        if target.kind == "test_suite" and not target.attrs.get("tests"):
            for t in self.ws.all_targets(target.label.package):
                if t.rule_class is not None and t.rule_class.test and "manual" not in t.tags:
                    out.append(("$implicit_tests", t.label))
        return out

    def deps_of(self, label: Label) -> list[Label]:
        """Direct dependencies (labels must exist)."""
        target = self.ws.target(label)
        return [lbl for _, lbl in self._edges(target)]

    def closure(self, roots: set[Label], depth: int | None, *, forward: bool) -> set[Label]:
        seen = set(roots)
        frontier = list(roots)
        level = 0
        while frontier and (depth is None or level < depth):
            nxt: list[Label] = []
            for lbl in frontier:
                for dep in self.deps_of(lbl):
                    if dep not in seen:
                        self.ws.target(dep)
                        seen.add(dep)
                        nxt.append(dep)
            frontier = nxt
            level += 1
        return seen

    def rclosure(self, universe: set[Label], targets: set[Label], depth: int | None) -> set[Label]:
        reverse: dict[Label, set[Label]] = {}
        for lbl in universe:
            for dep in self.deps_of(lbl):
                reverse.setdefault(dep, set()).add(lbl)
        seen = {t for t in targets if t in universe}
        frontier = list(seen)
        level = 0
        while frontier and (depth is None or level < depth):
            nxt = []
            for lbl in frontier:
                for user in reverse.get(lbl, ()):
                    if user not in seen:
                        seen.add(user)
                        nxt.append(user)
            frontier = nxt
            level += 1
        return seen

    _last_path: list[Label] = []  # noqa: RUF012 - the most recent somepath() result, start to end

    def paths(self, src: set[Label], dst: set[Label], *, all_paths: bool) -> set[Label]:
        self._last_path = []
        if all_paths:
            forward = self.closure(src, None, forward=True)
            reverse = self.rclosure(forward, dst & forward, None)
            return forward & reverse
        for s in sorted(src, key=str):
            parent: dict[Label, Label | None] = {s: None}
            queue = [s]
            while queue:
                cur = queue.pop(0)
                if cur in dst:
                    path = []
                    node: Label | None = cur
                    while node is not None:
                        path.append(node)
                        node = parent[node]
                    self._last_path = list(reversed(path))
                    return set(path)
                for dep in self.deps_of(cur):
                    if dep not in parent:
                        parent[dep] = cur
                        queue.append(dep)
        return set()

    def tests(self, labels: set[Label]) -> set[Label]:
        out: set[Label] = set()
        for lbl in labels:
            out |= self._expand_test(lbl, set())
        return out

    def _expand_test(self, lbl: Label, seen: set[Label]) -> set[Label]:
        if lbl in seen:
            return set()
        seen.add(lbl)
        t = self.ws.target(lbl)
        if t.kind == "test_suite":
            out: set[Label] = set()
            explicit = t.attrs.get("tests")
            if explicit:
                for item in explicit:
                    out |= self._expand_test(parse_label(item, lbl.package), seen)
            else:
                for other in self.ws.all_targets(lbl.package):
                    if other.rule_class is not None and other.rule_class.test and "manual" not in other.tags:
                        out.add(other.label)
            want = [x for x in t.attrs.get("tags") or [] if x != "manual"]
            if want:
                out = {x for x in out if _tag_match(self.ws.target(x), want)}
            return out
        if t.rule_class is not None and t.rule_class.test:
            return {lbl}
        return set()


def _select_repr(value: Select) -> str:
    """A select() the way Bazel prints it in errors: Label values as Label("...")."""
    parts = []
    for kind, part in value.parts:
        if kind == "select":
            body = ", ".join(
                f'"{k}": ' + (f'Label("{v}")' if isinstance(v, str) and v.startswith("//") else _starlark_repr(v))
                for k, v in part.items()
            )
            parts.append(f"select({{{body}}})")
        else:
            parts.append(_starlark_repr(part))
    return " + ".join(parts)


def _build_value(value: Any, akind: str, package: str) -> str:
    """An attribute value as ``bazel query --output=build`` prints it (labels canonical, strings double-quoted)."""
    import json

    if isinstance(value, Select):
        return repr(value)
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        if akind in ("label", "output"):
            value = str(parse_label(value, package))
        return json.dumps(value)
    if isinstance(value, list):
        items = value
        if akind in ("label_list", "output_list"):
            items = [str(parse_label(v, package)) for v in value]
        return "[" + ", ".join(_build_value(v, "", package) for v in items) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(str(k))}: {_build_value(v, '', package)}" for k, v in value.items()) + "}"
    return str(value)


def _macro_name_ok(name: str, macro: str) -> bool:
    return name == macro or any(name.startswith(macro + sep) and len(name) > len(macro) + 1 for sep in "_-.")


def _canonical(label: Label) -> str:
    """A label as Bazel prints it in analysis messages: ``@@repo//pkg:name`` outside the main repository."""
    return f"@@{label.repo}//{label.package}:{label.name}" if label.repo else str(label)


def _tag_match(target: Target, filters: list[str]) -> bool:
    tags = set(target.tags) | {target.attrs.get("size") or "medium"}
    # Bazel ignores a positive "manual" filter: manual tests are never selected by tag filters.
    pos = [f for f in filters if not f.startswith("-") and f != "manual"]
    neg = [f[1:] for f in filters if f.startswith("-")]
    if any(n in tags for n in neg):
        return False
    return not pos or any(p in tags for p in pos)


def _attr_string(target: Target, attr: str) -> str:
    value = target.attrs.get(attr)
    if value is None:
        rc = target.rule_class
        if attr == "size" and rc is not None and rc.test:
            return "medium"
        akind = rc.attrs.get(attr) if rc else None
        return "[]" if akind and "list" in akind else ""
    if isinstance(value, list):
        if all(isinstance(v, str) for v in value):
            items = []
            for v in value:
                try:
                    items.append(str(parse_label(v, target.label.package)) if attr not in ("tags", "args") else v)
                except BazelError:
                    items.append(v)
            return "[" + ", ".join(items) + "]"
        return str(value)
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


# ------------------------------------------------------------------------------------- public facade


@dataclass
class Result:
    """What a simulated command produced."""

    ok: bool
    output: str = ""
    errors: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    phase: str = ""
    skipped: list[str] = field(default_factory=list)  # incompatible targets a wildcard skipped (tests: SKIPPED)

    def __bool__(self) -> bool:
        """A result is truthy when the command succeeded."""
        return self.ok

    @property
    def error(self) -> str:
        """All errors joined: handy for ``assert "not visible" in result.error``."""
        return "\n".join(self.errors)


class Bazel:
    """Command-shaped access to a simulated workspace: ``bazel.query(...)``, ``bazel.build(...)``, and so on."""

    def __init__(self, files: dict[str, str]) -> None:
        """Evaluate ``files`` (workspace-relative path to content) as a workspace."""
        self.ws = Workspace(files)
        self.ws._current_command = "build"

    # -- helpers -----------------------------------------------------------------------------------

    def _ensure_module(self) -> None:
        if self.ws.module_error:
            raise BazelError(self.ws.module_error)

    def target(self, label: str) -> Target:
        """Load one target. Raises BazelError for missing packages, targets, and loading errors."""
        self._ensure_module()
        return self.ws.target(parse_label(label))

    def exists(self, label: str) -> bool:
        """True when the label names a target (loading errors count as 'no')."""
        try:
            self.target(label)
            return True
        except BazelError:
            return False

    def packages(self) -> list[str]:
        """Every package in the workspace, as ``//pkg`` strings."""
        return [f"//{p}" for p in self.ws.package_names]

    def printed(self) -> list[str]:
        """Lines printed by print() while loading packages (load them first)."""
        out: list[str] = []
        for pkg in self.ws._packages.values():
            out.extend(pkg.prints)
        return out

    def attr(self, label: str, name: str, *flags: str) -> Any:
        """An attribute's value; with flags, the select()-resolved value in that configuration."""
        t = self.target(label)
        if not flags:
            value = t.attrs.get(name)
            if isinstance(value, Select):
                raise BazelError(f"attribute '{name}' of {t.label} is configurable; pass flags to resolve it")
            return value
        self.ws._current_command = "cquery"
        cfg, _ = Config.parse(list(flags), self.ws)
        return _Analyzer(self.ws, cfg).resolve(t, name)

    # -- commands -----------------------------------------------------------------------------------

    def query(self, expr: str, *flags: str) -> list[str]:
        """``bazel query EXPR [flags]``: labels, sorted like Bazel's default output. Raises BazelError on errors.

        ``--universe_scope=PATTERNS`` or ``--infer_universe_scope`` enables ``allrdeps``, as in Bazel.
        """
        self._ensure_module()
        self.ws._current_command = "query"
        universe: list[str] | None = None
        flags = tuple(_expand_bazelrc(self.ws, list(flags)))  # query reads common and query lines only
        for flag in flags:
            if flag.startswith("--universe_scope="):
                universe = [p for p in flag.split("=", 1)[1].split(",") if p]
            elif flag == "--infer_universe_scope":
                universe = []
        q = _Query(self.ws, None, configured=False, universe=universe)
        return [str(lbl) for lbl in q.run(expr)]

    def cquery(self, expr: str, *flags: str) -> list[str]:
        """``bazel cquery EXPR [flags]``: like query, but select() is resolved for the given flags."""
        self._ensure_module()
        self.ws._current_command = "cquery"
        cfg, _ = Config.parse(list(flags), self.ws)
        an = _Analyzer(self.ws, cfg)
        q = _Query(self.ws, an, configured=True)
        return [str(lbl) for lbl in q.run(expr)]

    def _expand(self, patterns: list[str], *, skip_manual: bool) -> tuple[set[Label], set[Label]]:
        # Patterns apply left to right: "-- //... -//x/..." excludes, "-- -//x/... //..." adds them back.
        include: set[Label] = set()
        exclude: set[Label] = set()
        self._explicit: set[Label] = set()
        q = _Query(self.ws, None, configured=False)
        q.skip_manual = skip_manual
        for p in patterns:
            if p.startswith("-"):
                removed = q.pattern(p[1:])
                include -= removed
                exclude |= removed
                self._explicit -= removed
            else:
                found = q.pattern(p)
                include |= found
                if not _is_wildcard(p):
                    self._explicit |= found
        return include, exclude

    def build(self, *args: str) -> Result:
        """``bazel build PATTERNS [flags]`` up to the end of analysis (nothing is compiled)."""
        return self._build("build", list(args))

    def test(self, *args: str) -> Result:
        """``bazel test PATTERNS [flags]``: analysis plus which tests would run (``Result.tests``)."""
        return self._build("test", list(args))

    def _build(self, command: str, args: list[str]) -> Result:
        self.ws._current_command = command
        if self.ws.module_error:
            return Result(False, self.ws.module_error, [self.ws.module_error], phase="loading")
        try:
            cfg, patterns = Config.parse(args, self.ws)
        except BazelError as exc:
            return Result(False, f"ERROR: {exc}", [str(exc)], phase="options")
        if "--" in patterns:
            patterns.remove("--")
        if not patterns:
            msg = f"No targets specified. Usage: bazel {command} [options] <target patterns>"
            return Result(False, f"WARNING: Usage: bazel {command} <options> <targets>.\n{msg}", [msg], phase="loading")
        try:
            targets, _excluded = self._expand(patterns, skip_manual=True)
        except BazelError as exc:
            err = f"Skipping '{patterns[0]}': {exc}"
            return Result(
                False, f"ERROR: {err}\nERROR: Build did NOT complete successfully", [str(exc)], phase="loading"
            )
        an = _Analyzer(self.ws, cfg)
        test_labels: set[Label] = set()
        if command == "test":
            q = _Query(self.ws, an, configured=True)
            test_labels = q.tests(targets)
            if cfg.test_tag_filters:
                test_labels = {t for t in test_labels if _tag_match(self.ws.target(t), cfg.test_tag_filters)}
            if cfg.test_size_filters:
                test_labels = {
                    t for t in test_labels if (self.ws.target(t).attrs.get("size") or "medium") in cfg.test_size_filters
                }
            if cfg.build_tests_only:
                targets = set(test_labels)
            else:
                targets = targets | test_labels
        # target_compatible_with: wildcards skip incompatible targets; naming one is an error.
        skipped: set[Label] = set()
        for lbl in sorted(targets, key=str):
            if an.incompatible(lbl):
                if lbl in self._explicit:
                    msg = an.incompatible_message(lbl)
                    out = f"ERROR: {msg}\nERROR: Build did NOT complete successfully"
                    if command == "test":
                        out += "\nERROR: No test targets were found, yet testing was requested"
                    return Result(False, out, [msg], phase="analysis")
                skipped.add(lbl)
        targets -= skipped
        skipped_tests = sorted(str(t) for t in test_labels & skipped)
        test_labels -= skipped
        for lbl in sorted(targets, key=str):
            an.check(lbl)
        errors = list(dict.fromkeys(an.errors))
        built = sorted(str(t) for t in targets)
        tests = sorted(str(t) for t in test_labels)
        skip_list = sorted(str(t) for t in skipped)
        if errors:
            out = "\n".join(f"ERROR: {e}" for e in errors)
            out += "\nERROR: Analysis of target failed; build aborted\nERROR: Build did NOT complete successfully"
            return Result(False, out, errors, built, tests, phase="analysis", skipped=skip_list)
        missing = sorted(set(an.missing_inputs))
        if missing:
            errs = [f"missing input file '{m}'" for m in missing]
            out = "\n".join(f"ERROR: {e}" for e in errs) + "\nERROR: Build did NOT complete successfully"
            return Result(False, out, errs, built, tests, phase="execution", skipped=skip_list)
        lines = [
            f"INFO: Analyzed {len(built) + len(skip_list)} target{'s' if len(built) + len(skip_list) != 1 else ''} (simulated)."
        ]
        if skip_list and not built:
            lines.extend(f"Target {t} was skipped" for t in skip_list)
        if command == "test":
            for t in skipped_tests:
                lines.append(f"{t:<72}SKIPPED")
            for t in tests:
                lines.append(f"{t:<60} (would run)")
            if not tests and skipped_tests:
                n = len(skipped_tests)
                lines.append(
                    f"Executed 0 out of {n} test{'s' if n != 1 else ''}: {n} {'was' if n == 1 else 'were'} skipped."
                )
                return Result(True, "\n".join(lines), [], built, tests, phase="done", skipped=skip_list)
            if not tests:
                lines.append("ERROR: No test targets were found, yet testing was requested")
                return Result(
                    False,
                    "\n".join(lines),
                    ["No test targets were found, yet testing was requested"],
                    built,
                    tests,
                    "analysis",
                )
            total = len(tests) + len(skipped_tests)
            skipped_note = (
                f": {len(skipped_tests)} {'was' if len(skipped_tests) == 1 else 'were'} skipped"
                if skipped_tests
                else ""
            )
            lines.append(
                f"Executed 0 out of {total} tests{skipped_note} (the simulator analyzes; it does not run tests)."
            )
        else:
            lines.append("INFO: Build completed successfully (analysis only: the simulator does not run actions).")
        return Result(True, "\n".join(lines), [], built, tests, phase="done", skipped=skip_list)

    def run_command(self, command_line: str) -> Result:
        """Run a command line such as ``bazel query 'deps(//app:hello)'`` and format its output like Bazel.

        DEBUG lines from print() and loading WARNINGs come first, for packages this command loaded (Bazel caches
        loaded packages, so a second command prints them only if the package changed).
        """
        before = set(self.ws._packages)
        result = self._run_command(command_line)
        events = list(self.ws.module.warnings)
        for name, pkg in self.ws._packages.items():
            if name not in before:
                events.extend(pkg.events)
        if events:
            result.output = "\n".join([*events, result.output]) if result.output else "\n".join(events)
        return result

    def _cquery_suffix(self, an: _Analyzer, label: str) -> str:
        t = self.ws.target(parse_label(label))
        if t.kind == "source file":
            return "(null)"
        if t.kind == "generated file" and t.generating_rule is not None:
            t = self.ws.target(t.generating_rule)
        return f"({an.config_id(t, 7)})"

    def _format_build(self, label: str) -> str:
        t = self.ws.target(parse_label(label))
        if not t.is_rule or t.external:
            return ""
        lines = [f"# {t.location}", f"{t.kind}("]
        lines.append(f'  name = "{t.name}",')
        order = ["visibility"] if "visibility" in t.explicit else []
        order += [a for a in ("generator_name", "generator_function", "generator_location") if a in t.attrs]
        order += [a for a in t.explicit if a != "visibility"]
        rc = t.rule_class
        for attr in order:
            value = t.attrs.get(attr)
            akind = rc.attrs.get(attr, "") if rc else ""
            lines.append(f"  {attr} = {_build_value(value, akind, t.label.package)},")
        lines.append(")")
        lines.append(f"# Rule {t.name} instantiated at (most recent call last):")
        frames = t.stack or ((t.location, "<toplevel>"),)
        width = max(len(loc) for loc, _ in frames)
        lines.extend(f"#   {loc:<{width}} in {fn}" for loc, fn in frames)
        return "\n".join(lines)

    def _ranks(self, labels: list[str], *, longest: bool) -> list[tuple[int, str]]:
        """``--output=minrank`` / ``maxrank``: each target's shortest or longest distance from a root.

        A root is a target nothing else in the result depends on; only edges inside the result count.
        """
        q = _Query(self.ws, None, configured=False)
        members = [parse_label(lbl) for lbl in labels]
        inside = set(members)
        edges = {m: [d for d in q.deps_of(m) if d in inside] for m in members}
        has_parent = {d for ds in edges.values() for d in ds}
        rank: dict[Label, int] = {m: 0 for m in members if m not in has_parent}
        frontier = list(rank)
        while frontier:
            nxt = []
            for m in frontier:
                for d in edges[m]:
                    r = rank[m] + 1
                    if d not in rank or (longest and r > rank[d] and r <= len(members)):
                        rank[d] = r
                        nxt.append(d)
            frontier = nxt
        return sorted(
            ((r, str(lbl)) for lbl, r in rank.items()),
            key=lambda x: (x[0], x[1].startswith("@"), x[1]),
        )

    def _run_command(self, command_line: str) -> Result:
        import shlex

        try:
            words = shlex.split(command_line)
        except ValueError as exc:
            return Result(False, f"ERROR: {exc}", [str(exc)])
        if words and words[0] in ("bazel", "bazelisk"):
            words = words[1:]
        if words and words[0] == "pixi":
            words = words[3:] if len(words) > 2 and words[1] == "run" else words
        if not words:
            return Result(False, "Usage: bazel <command> <options> ...", ["no command"])
        cmd, rest = words[0], words[1:]
        try:
            if cmd in ("query", "cquery"):
                flags, exprs = _split_flags(rest)
                if len(exprs) != 1:
                    raise BazelError(f"{cmd} expects exactly one query expression (quote it)")
                fmt = next((f.split("=", 1)[1] for f in flags if f.startswith("--output")), "label")
                cfg_flags = [f for f in flags if not f.startswith("--output")]
                labels = self.query(exprs[0], *cfg_flags) if cmd == "query" else self.cquery(exprs[0], *cfg_flags)
                labels = list(dict.fromkeys(labels))  # each target once, even if reached through two equal labels
                suffix: Any = lambda _lbl: ""  # noqa: E731
                if cmd == "cquery":
                    self.ws._current_command = "cquery"
                    an = _Analyzer(self.ws, Config.parse(list(cfg_flags), self.ws)[0])
                    suffix = lambda lbl: " " + self._cquery_suffix(an, lbl)  # noqa: E731
                if fmt == "label_kind":
                    text = "\n".join(
                        f"{self.ws.target(parse_label(lbl)).kind_string()} {lbl}{suffix(lbl)}" for lbl in labels
                    )
                elif fmt == "package":
                    text = "\n".join(sorted({lbl.split(":")[0].lstrip("/") for lbl in labels}))
                elif fmt == "label":
                    text = "\n".join(f"{lbl}{suffix(lbl)}" for lbl in labels)
                elif fmt in ("minrank", "maxrank") and cmd == "query":
                    text = "\n".join(f"{r} {lbl}" for r, lbl in self._ranks(labels, longest=fmt == "maxrank"))
                elif fmt == "build" and cmd == "query":
                    text = "\n".join(b for b in (self._format_build(lbl) for lbl in labels) if b)
                else:
                    supported = (
                        "label, label_kind, and package"
                        if cmd == "cquery"
                        else ("label, label_kind, package, minrank, maxrank, and build")
                    )
                    raise BazelError(f"the simulator supports --output={supported}, not '{fmt}'")
                if not labels:
                    text = "INFO: Empty results"
                return Result(True, text, targets=labels)
            if cmd in ("build", "test"):
                return self._build(cmd, rest)
            if cmd == "run":
                if "--" in rest:
                    rest = rest[: rest.index("--")]  # what follows "--" is the program's own arguments
                res = self._build("build", rest)
                if not res.ok:
                    return res
                t = self.target(next(a for a in rest if not a.startswith("-")))
                if t.rule_class is None or not t.rule_class.executable:
                    msg = f"Cannot run target {t.label}: Not executable"
                    return Result(False, f"ERROR: {msg}", [msg])
                path = f"{t.label.package}/{t.name}"
                if t.kind in ("go_binary", "go_test"):
                    path = f"{t.label.package}/{t.name}_/{t.name}"  # rules_go's output layout
                res.output += f"\nINFO: Running command line: bazel-bin/{path} (simulated: not executed)"
                return res
            if cmd == "version":
                return Result(True, f"Bazel {BAZEL_VERSION} (simulated)")
            if cmd in ("clean", "shutdown", "info", "mod", "fetch"):
                return Result(True, f"INFO: '{cmd}' does nothing in the simulator; try it in a real workspace.")
            return Result(False, f"Command '{cmd}' not found. Try 'bazel help'.", [f"unknown command {cmd}"])
        except BazelError as exc:
            return Result(False, f"ERROR: {exc}", [str(exc)])


# Options whose value may follow as a separate word: ``-c opt``, ``--platforms //:p``.
_VALUE_OPTIONS = frozenset(
    {
        "-c",
        "--compilation_mode",
        "--define",
        "--platforms",
        "--output",
        "--universe_scope",
        "--config",
        "--test_tag_filters",
        "--test_size_filters",
    }
)


def _is_wildcard(pattern: str) -> bool:
    """True for target patterns that name many targets (//..., //pkg:all, //pkg:*), which skip incompatible ones."""
    body = pattern.split(":", 1)
    return (
        pattern.endswith("...")
        or "/...:" in pattern
        or "...:" in pattern
        or (len(body) == 2 and body[1] in ("all", "*", "all-targets"))
    )


def _split_flags(words: list[str]) -> tuple[list[str], list[str]]:
    """Split command-line words into options (``-c opt`` joined as ``-c=opt``) and positional arguments."""
    flags: list[str] = []
    positional: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        if word in _VALUE_OPTIONS and i + 1 < len(words):
            flags.append(f"{'--compilation_mode' if word == '-c' else word}={words[i + 1]}")
            i += 2
            continue
        (flags if word.startswith("-") else positional).append(word)
        i += 1
    return flags, positional


def load_workspace(files: dict[str, str]) -> Bazel:
    """Create a simulator for an in-memory workspace (paths relative to the workspace root)."""
    return Bazel(files)


# ------------------------------------------------------------------------------------- exercise runner


def run_checks(files: dict[str, str], tests_source: str) -> list[dict[str, Any]]:
    """Run an exercise's check functions against ``files``. Each check is ``def test_x(bazel): ...``.

    Returns one ``{"name", "ok", "msg"}`` per check, in source order. The browser and the course's checker both
    call this, so a check passes in one exactly when it passes in the other.
    """
    namespace: dict[str, Any] = {"BazelError": BazelError, "re": re}
    exec(compile(tests_source, "<checks>", "exec"), namespace)
    names = [n for n, v in namespace.items() if n.startswith("test_") and callable(v)]
    results: list[dict[str, Any]] = []
    for name in names:
        bazel = Bazel(files)
        label = name[5:].replace("_", " ")
        try:
            namespace[name](bazel)
            results.append({"name": label, "ok": True, "msg": ""})
        except AssertionError as exc:
            results.append({"name": label, "ok": False, "msg": str(exc) or "assertion failed"})
        except BazelError as exc:
            results.append({"name": label, "ok": False, "msg": f"Bazel reported an error: {exc}"})
        except Exception as exc:  # a learner's BUILD file can raise anything
            results.append({"name": label, "ok": False, "msg": f"{type(exc).__name__}: {exc}"})
    return results
