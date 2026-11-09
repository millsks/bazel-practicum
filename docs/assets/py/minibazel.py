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
    "constraint_setting": _rc("constraint_setting", {"default_constraint_value": "label"}),
    "constraint_value": _rc("constraint_value", {"constraint_setting": "label"}, mandatory=("constraint_setting",)),
    "py_library": _rc("py_library", _PY, provides=("PyInfo",), needs={"deps": _PYDEP}, exts={"srcs": (".py",)}),
    "py_binary": _rc(
        "py_binary",
        _PY_EXE,
        provides=("PyInfo",),
        needs={"deps": _PYDEP},
        exts={"srcs": (".py",)},
        executable=True,
        macro="py_binary",
    ),
    "py_test": _rc(
        "py_test",
        {**_PY_EXE, **_TEST},
        provides=("PyInfo",),
        needs={"deps": _PYDEP},
        exts={"srcs": (".py",)},
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
        return f"{self.kind} rule" if self.is_rule else self.kind

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
    _CURRENT.prints.append(sep.join(str(a) for a in args))


def _fail(*args: Any, attr: str | None = None, sep: str = " ") -> None:
    msg = sep.join(str(a) for a in args)
    raise _Fail(f"Error in fail: {attr + ': ' if attr else ''}{msg}")


class _Ctx:
    """Mutable state for the file being evaluated (prints go here)."""

    def __init__(self) -> None:
        self.prints: list[str] = []


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


class _Extension:
    def __init__(self, module: _ModuleInfo, bzl: str, name: str) -> None:
        self._module = module
        self._bzl = bzl
        self._name = name
        self.declared: set[str] = set()

    def __getattr__(self, tag: str) -> Any:
        if tag.startswith("_"):
            raise AttributeError(tag)

        def call(**kw: Any) -> None:
            if self._bzl.endswith("pip.bzl") and tag == "parse":
                hub = kw.get("hub_name")
                lock = kw.get("requirements_lock") or kw.get("requirements_linux") or kw.get("requirements_darwin")
                if not hub:
                    raise _Fail("pip.parse: missing mandatory attribute 'hub_name'")
                if not lock:
                    raise _Fail("pip.parse: one of 'requirements_lock' or a platform-specific lock file is required")
                self._module.pip_hubs[hub] = str(lock)
                self.declared.add(hub)
            elif self._bzl.endswith("python.bzl") and tag == "toolchain":
                self._module.python_versions.append(str(kw.get("python_version", "")))
            elif self._bzl.endswith("extensions.bzl") and tag == "download" and "go" in self._bzl:
                self._module.go_versions.append(str(kw.get("version", "")))
                self.declared.add("go_sdk")
            elif tag in ("from_file", "host"):
                self.declared.add("go_sdk")

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
            if apparent in mod.deps:
                raise _Fail(f"The repo name '{apparent}' is already being used by another bazel_dep")
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
            return _Extension(mod, bzl, name)

        def use_repo(ext: _Extension, *names: str, **aliases: str) -> None:
            for n in names:
                if n not in ext.declared and not (n == "go_sdk"):
                    raise _Fail(
                        f'module extension "{ext._name}" from "{ext._bzl}" does not generate repository '
                        f'"{n}", yet it is imported as "{n}" in the usage at MODULE.bazel'
                    )
                mod.repos[n] = ext._name
            for alias, n in aliases.items():
                if n not in ext.declared:
                    raise _Fail(f'module extension "{ext._name}" does not generate repository "{n}"')
                mod.repos[alias] = ext._name
                if n in mod.pip_hubs:
                    mod.pip_hubs[alias] = mod.pip_hubs[n]

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
        """Repositories the main repository can see by apparent name."""
        return {*self.module.deps, *self.module.repos, "bazel_tools", ""}

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
        _CURRENT = _Ctx()
        try:
            env = self._build_env(pkg, path)
            _Exec.run(source, path, env)
        finally:
            pkg.prints.extend(_CURRENT.prints)
            _CURRENT = saved
        self._attach_source_files(pkg)

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
                        # Bazel creates an input-file target for every same-package label a rule mentions; a
                        # missing file only fails later, at execution ("missing input file").
                        if not self._crosses_subpackage(pkg.name, label.name):
                            pkg.targets[label.name] = Target(label, "source file", location=pkg.build_file)
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

    def _crosses_subpackage(self, package: str, name: str) -> bool:
        path = f"{package}/{name}" if package else name
        return self.package_of_path(path) != package

    def _is_file_in_package(self, package: str, name: str) -> bool:
        path = f"{package}/{name}" if package else name
        return path in self.files and self.package_of_path(path) == package

    # ------------------------------------------------------------------ environments

    def _native_functions(self, pkg: _Package, path: str) -> dict[str, Any]:
        def rule_fn(kind: str) -> Any:
            def create(*args: Any, **kwargs: Any) -> None:
                where = self._call_location(pkg.build_file)
                if args:
                    raise _Fail(f"{where}: Error in {kind}: {kind}() does not accept positional arguments")
                self._declare(pkg, kind, kwargs, where)

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
        return {k: v for k, v in scope.items() if k not in env or env[k] is not v}

    def _bzl_env(self, pkg: _Package, path: str, bzl_package: str) -> dict[str, Any]:
        native = self._native_functions(pkg, path)
        env: dict[str, Any] = {**_SAFE_BUILTINS, "print": _starlark_print, "fail": _fail}
        env["select"] = native["select"]
        env["struct"] = _Struct
        env["Label"] = lambda s: str(parse_label(s, bzl_package))
        env["depset"] = lambda direct=None, **k: list(direct or [])
        env["native"] = _Struct(**{k: v for k, v in native.items() if not k.startswith("_")})

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
            attrs["visibility"] = list(pkg.default_visibility)
        if "testonly" not in attrs:
            attrs["testonly"] = rc.test or pkg.default_testonly
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
        if akind in ("label", "output", "string"):
            if not isinstance(value, str):
                raise _Fail(f"{where}: expected value of type 'string' for attribute '{attr}' in '{kind}' rule")
            if akind == "label":
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
        if label.repo:
            return self._external_target(label)
        pkg = self.package(label.package)
        if label.name in pkg.targets:
            return pkg.targets[label.name]
        # a source file that exists but that no rule referenced is still a target
        if self._is_file_in_package(label.package, label.name):
            t = Target(label, "source file", location=pkg.build_file)
            pkg.targets[label.name] = t
            return t
        hint = ""
        full = f"{label.package}/{label.name}" if label.package else label.name
        if full in self.files:
            owner = self.package_of_path(full)
            hint = (
                f"; however, a source file of this name exists.  (Perhaps add "
                f"'exports_files([\"{label.name}\"])' to {pkg.build_file}?)"
                if owner == label.package
                else f" (perhaps you meant //{owner}:{full[len(owner) + 1 :] if owner else full})"
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
            wanted = _normalize_dist(label.package)
            if label.name not in (label.package, "pkg", "whl", "data", "dist_info"):
                raise BazelError(f"no such target '{label}'")
            available = self.pip_packages(label.repo)
            if wanted not in available:
                raise BazelError(
                    f"no such package '@@rules_python++pip+{label.repo}//{label.package}': BUILD file not found in "
                    f"directory '{label.package}' of external repository @@rules_python++pip+{label.repo}. "
                    f"('{label.package}' is not in {self.module.pip_hubs[label.repo]}; add it to your requirements "
                    "and re-lock.)"
                )
            return Target(label, "py_library", {"visibility": ["//visibility:public"]}, external=True)
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
                    raise BazelError(
                        f"While parsing option --compilation_mode={cfg.compilation_mode}: Not a valid compilation "
                        "mode: (should be dbg, opt or fastbuild)"
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
                value: Any = val if eq else "true"
                cfg.flags[str(parse_label(key))] = value
            elif a.startswith("--no//") or a.startswith("--no@"):
                cfg.flags[str(parse_label(a[4:]))] = "false"
            elif a.startswith("--"):
                name, eq, val = a[2:].partition("=")
                cfg.values[name] = val if eq else "true"
            else:
                rest.append(a)
            i += 1
        cfg.values.setdefault("compilation_mode", cfg.compilation_mode)
        return cfg, rest


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
    command = ws._current_command
    inherited = {"build": ["common", "build"], "test": ["common", "build", "test"], "query": ["common", "query"]}
    inherited["cquery"] = ["common", "build", "cquery"]
    prefix: list[str] = []
    for section in inherited.get(command, ["common"]):
        prefix.extend(lines.get(section, []))
    out: list[str] = []
    for a in [*prefix, *args]:
        if a.startswith("--config"):
            name = a.split("=", 1)[1] if "=" in a else ""
            found = False
            for section in inherited.get(command, ["common"]):
                extra = lines.get(f"{section}:{name}")
                if extra:
                    out.extend(extra)
                    found = True
            if not found:
                raise BazelError(f"Config value '{name}' is not defined in any .rc file")
        else:
            out.append(a)
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
            if self._matches(cond):
                matching.append((label, cond))
        if not matching:
            if "//conditions:default" in conditions:
                return conditions["//conditions:default"]
            keys = "\n".join(f" {k}" for k in conditions)
            msg = no_match or (
                f'Configurable attribute "{attr}" doesn\'t match this configuration (would a default condition '
                f"help?).\nConditions checked:\n{keys}"
            )
            raise BazelError(f"{target.location}: {target.label}: {msg}")
        if len(matching) > 1:
            specialized = [m for m in matching if all(self._refines(m[1], o[1]) for o in matching if o is not m)]
            if len(specialized) != 1:
                names = ", ".join(str(m[0]) for m in matching)
                raise BazelError(
                    f"{target.location}: {target.label}: Illegal ambiguous match on configurable attribute "
                    f'"{attr}" in {target.label}:\n{names}\nMultiple matches are not allowed unless one is '
                    "unambiguously more specialized or they resolve to the same value."
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
            out.add(("flag", f"{k}={v}"))
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

    def _matches(self, cond: Target) -> bool:
        if cond.kind == "constraint_value" or (cond.external and cond.kind == "constraint_value"):
            return str(cond.label) in self.platform_constraints()
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
            current = self.cfg.flags.get(str(flag_label))
            if current is None:
                default = setting.attrs.get("build_setting_default")
                current = (
                    ("true" if default else "false") if isinstance(default, bool) else str(default if default else "")
                )
                if flag_label.repo == "rules_python" and flag_label.name == "python_version":
                    current = self.ws.module.python_versions[0] if self.ws.module.python_versions else ""
            if str(current).lower() != str(v).lower():
                return False
        constraints = cond.attrs.get("constraint_values") or []
        if constraints:
            have = self.platform_constraints()
            for c in constraints:
                if str(parse_label(c, pkg)) not in have:
                    return False
        return True

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
            if attr not in ("$implicit_tests",) and not self.visible(dep, target):
                self.errors.append(
                    f"{where}: in {target.kind} rule {target.label}: Visibility error:\n"
                    f"target '{dep.label}' is not visible from\ntarget '{target.label}'\n"
                    "Recommendation: modify the visibility declaration if you think the dependency is legitimate. "
                    "For more info see https://bazel.build/concepts/visibility"
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
            if needs and not self._provides(dep, needs):
                names = " or ".join(f"'{n}'" for n in needs)
                suffix = (
                    f". Since this rule was created by the macro '{rc.macro}', the error might have been caused by "
                    "the macro implementation"
                    if rc.macro
                    else ""
                )
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
        self._rule_specific(target)

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
        if dep.external or dep.label.package == user.label.package:
            return True
        if dep.kind == "generated file" and dep.generating_rule is not None:
            dep = self.ws.target(dep.generating_rule)
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
                    specs = group.attrs.get("packages") or []
                    for spec in specs:
                        if spec == "public":
                            return True
                        neg = spec.startswith("-")
                        spec = spec.lstrip("-")
                        body = spec[2:] if spec.startswith("//") else spec
                        hit = (
                            (body.endswith("/...") and (user_pkg == body[:-4] or user_pkg.startswith(body[:-4] + "/")))
                            or body == "..."
                            or body == user_pkg
                        )
                        if hit:
                            return not neg
                    for inc in group.attrs.get("includes") or []:
                        if self._allowed([inc], group.label.package, user_pkg, seen):
                            return True
        return False

    def _rule_specific(self, target: Target) -> None:
        where = target.location
        if target.kind in ("py_binary", "py_test"):
            srcs = self.resolve(target, "srcs") or []
            main = self.resolve(target, "main")
            if not main and not target.attrs.get("main_module"):
                default = f"{target.name}.py"
                names = [parse_label(s, target.label.package).name for s in srcs]
                if default not in names:
                    self.errors.append(
                        f"{where}: in {target.kind} rule {target.label}: \nError in fail: corresponding default "
                        f"'{default}' does not appear in srcs. Add it or override default file name with a 'main' "
                        "attribute"
                    )
            elif main:
                names = [str(parse_label(s, target.label.package)) for s in srcs]
                if str(parse_label(main, target.label.package)) not in names:
                    self.errors.append(
                        f"{where}: in {target.kind} rule {target.label}: \nError in fail: could not find '{main}' as "
                        "specified by 'main' attribute"
                    )
        if target.kind == "genrule":
            self._check_make_vars(target)
        if target.kind in ("go_binary", "go_test", "go_library"):
            srcs = self.resolve(target, "srcs") or []
            embed = self.resolve(target, "embed") or []
            if target.kind == "go_library" and not srcs and not embed:
                pass

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
        where = f"{target.location}: in cmd attribute of genrule rule {target.label}"
        for m in re.finditer(
            r"\$\((location|locations|execpath|execpaths|rootpath|rootpaths|rlocationpath)\s+([^)]+)\)", cmd
        ):
            ref = m.group(2).strip()
            try:
                label = str(parse_label(ref, pkg))
            except BazelError as exc:
                self.errors.append(f"{where}: {exc}")
                continue
            if label not in prereq:
                self.errors.append(
                    f"{where}: label '{label}' in $({m.group(1)}) expression is not a declared prerequisite of this rule"
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


_TOKEN = re.compile(r"\s*(?:(\()|(\))|(,)|(\+|\^|-(?=\s))|\"([^\"]*)\"|'([^']*)'|([^\s(),\"']+))")


class _Query:
    """A small `bazel query` evaluator: patterns, set operations, and the common functions."""

    def __init__(self, ws: Workspace, analyzer: _Analyzer | None, configured: bool) -> None:
        self.ws = ws
        self.an = analyzer or _Analyzer(ws, Config())
        self.configured = configured

    def run(self, expr: str) -> list[Label]:
        tokens = self._tokenize(expr)
        self.tokens = tokens
        self.pos = 0
        result = self._expr()
        if self.pos != len(self.tokens):
            raise BazelError(f"syntax error at '{self.tokens[self.pos][1]}'")
        return sorted(result, key=lambda lbl: (lbl.repo != "", str(lbl)))

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
            right = self._primary()
            left = left | right if tok[1] == "+" else left & right if tok[1] == "^" else left - right
        return left

    def _primary(self) -> set[Label]:
        kind, value = self._next()
        if kind == "(":
            out = self._expr()
            if self._next()[0] != ")":
                raise BazelError("syntax error: expected ')'")
            return out
        if kind != "word":
            raise BazelError(f"syntax error at '{value}'")
        nxt = self._peek()
        if nxt is not None and nxt[0] == "(":
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
        if fn == "allrdeps":
            need(1, 2)
            universe = self.closure(self.pattern("//..."), None, forward=True)
            depth = int(self._arg_word(args[1])) if n == 2 else None
            return self.rclosure(universe, self._arg_expr(args[0]), depth)
        if fn in ("somepath", "allpaths"):
            need(2)
            src, dst = self._arg_expr(args[0]), self._arg_expr(args[1])
            return self.paths(src, dst, all_paths=fn == "allpaths")
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
        raise BazelError(f"syntax error: unknown function '{fn}'")

    # ---------------------------------------------------------------- patterns

    def pattern(self, text: str) -> set[Label]:
        """Expand a target pattern: //..., //pkg/..., //pkg:all, //pkg:*, or a single label."""
        if text.startswith("@"):
            return {self.ws.target(parse_label(text)).label}
        t = text
        if t.startswith(":"):
            t = "//" + t
        elif not t.startswith("//"):
            t = "//" + t
        body = t[2:]
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

    def paths(self, src: set[Label], dst: set[Label], *, all_paths: bool) -> set[Label]:
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


def _tag_match(target: Target, filters: list[str]) -> bool:
    tags = set(target.tags) | {target.attrs.get("size") or "medium"}
    pos = [f for f in filters if not f.startswith("-")]
    neg = [f[1:] for f in filters if f.startswith("-")]
    if any(n in tags for n in neg):
        return False
    return not pos or any(p in tags for p in pos)


def _attr_string(target: Target, attr: str) -> str:
    value = target.attrs.get(attr)
    if value is None:
        rc = target.rule_class
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
        """``bazel query EXPR``: labels, sorted like Bazel's default output. Raises BazelError on errors."""
        self._ensure_module()
        self.ws._current_command = "query"
        q = _Query(self.ws, None, configured=False)
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
        include: set[Label] = set()
        exclude: set[Label] = set()
        q = _Query(self.ws, None, configured=False)
        q.skip_manual = skip_manual
        for p in patterns:
            if p.startswith("-"):
                exclude |= q.pattern(p[1:])
            else:
                include |= q.pattern(p)
        return include - exclude, exclude

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
        for lbl in sorted(targets, key=str):
            an.check(lbl)
        errors = list(dict.fromkeys(an.errors))
        built = sorted(str(t) for t in targets)
        tests = sorted(str(t) for t in test_labels)
        if errors:
            out = "\n".join(f"ERROR: {e}" for e in errors)
            out += "\nERROR: Analysis of target failed; build aborted\nERROR: Build did NOT complete successfully"
            return Result(False, out, errors, built, tests, phase="analysis")
        missing = sorted(set(an.missing_inputs))
        if missing:
            errs = [f"missing input file '{m}'" for m in missing]
            out = "\n".join(f"ERROR: {e}" for e in errs) + "\nERROR: Build did NOT complete successfully"
            return Result(False, out, errs, built, tests, phase="execution")
        lines = [f"INFO: Analyzed {len(built)} target{'s' if len(built) != 1 else ''} (simulated)."]
        if command == "test":
            for t in tests:
                lines.append(f"{t:<60} (would run)")
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
            lines.append(f"Executed 0 out of {len(tests)} tests (the simulator analyzes; it does not run tests).")
        else:
            lines.append("INFO: Build completed successfully (analysis only: the simulator does not run actions).")
        return Result(True, "\n".join(lines), [], built, tests, phase="done")

    def run_command(self, command_line: str) -> Result:
        """Run a command line such as ``bazel query 'deps(//app:hello)'`` and format its output like Bazel."""
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
                flags = [a for a in rest if a.startswith("-")]
                exprs = [a for a in rest if not a.startswith("-")]
                if len(exprs) != 1:
                    raise BazelError(f"{cmd} expects exactly one query expression (quote it)")
                fmt = next((f.split("=", 1)[1] for f in flags if f.startswith("--output")), "label")
                cfg_flags = [f for f in flags if not f.startswith("--output")]
                labels = self.query(exprs[0]) if cmd == "query" else self.cquery(exprs[0], *cfg_flags)
                if fmt == "label_kind":
                    text = "\n".join(f"{self.ws.target(parse_label(lbl)).kind_string()} {lbl}" for lbl in labels)
                elif fmt == "package":
                    text = "\n".join(sorted({lbl.split(":")[0].lstrip("/") for lbl in labels}))
                elif fmt == "label":
                    text = "\n".join(labels)
                else:
                    raise BazelError(f"the simulator supports --output=label, label_kind, and package, not '{fmt}'")
                if not labels:
                    text = "INFO: Empty results"
                return Result(True, text, targets=labels)
            if cmd in ("build", "test"):
                return self._build(cmd, rest)
            if cmd == "run":
                res = self._build("build", [rest[0]] if rest else [])
                if not res.ok:
                    return res
                t = self.target(rest[0])
                if t.rule_class is None or not t.rule_class.executable:
                    msg = f"Cannot run target {t.label}: Not executable"
                    return Result(False, f"ERROR: {msg}", [msg])
                res.output += f"\nINFO: Running command line: bazel-bin/{t.label.package}/{t.label.name} (simulated: not executed)"
                return res
            if cmd == "version":
                return Result(True, f"Bazel {BAZEL_VERSION} (simulated)")
            if cmd in ("clean", "shutdown", "info", "mod", "fetch"):
                return Result(True, f"INFO: '{cmd}' does nothing in the simulator; try it in a real workspace.")
            return Result(False, f"Command '{cmd}' not found. Try 'bazel help'.", [f"unknown command {cmd}"])
        except BazelError as exc:
            return Result(False, f"ERROR: {exc}", [str(exc)])


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
