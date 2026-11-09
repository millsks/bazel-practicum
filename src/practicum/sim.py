"""Load the Bazel simulator (``docs/assets/py/minibazel.py``) that the browser runs on Pyodide.

The simulator lives with the site so the browser and the checker run the very same file. This module imports it
from there by path.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_CACHE: dict[Path, ModuleType] = {}


def simulator_path(site_root: Path) -> Path:
    """Return the simulator's source file for a site.

    Args:
        site_root: The ``docs/`` directory.

    Returns:
        Path to ``assets/py/minibazel.py``.
    """
    return site_root / "assets" / "py" / "minibazel.py"


def load_simulator(site_root: Path) -> ModuleType:
    """Import the simulator from a site, once per path.

    Args:
        site_root: The ``docs/`` directory.

    Returns:
        The ``minibazel`` module.

    Raises:
        FileNotFoundError: If the site has no simulator.
    """
    path = simulator_path(site_root).resolve()
    if path in _CACHE:
        return _CACHE[path]
    if not path.is_file():
        raise FileNotFoundError(f"simulator not found: {path}")
    spec = importlib.util.spec_from_file_location(f"minibazel_{len(_CACHE)}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib always returns a spec for a .py path
        raise FileNotFoundError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _CACHE[path] = module
    return module
