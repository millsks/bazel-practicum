"""Locate the practicum repository root on disk."""

import os
from pathlib import Path

ROOT_ENV_VAR = "PRACTICUM_ROOT"


class WorkspaceNotFoundError(RuntimeError):
    """Raised when the practicum repository root cannot be located."""


def find_root(start: Path | None = None) -> Path:
    """Find the repository root containing ``pixi.toml`` and ``labs/``.

    The ``PRACTICUM_ROOT`` environment variable takes precedence over searching.

    Args:
        start: Directory to start searching upward from. Defaults to the current directory.

    Returns:
        The absolute path of the repository root.

    Raises:
        WorkspaceNotFoundError: If no matching directory exists at or above ``start``.
    """
    override = os.environ.get(ROOT_ENV_VAR)
    if override:
        root = Path(override).resolve()
        if _is_root(root):
            return root
        raise WorkspaceNotFoundError(f"{ROOT_ENV_VAR}={override} is not a practicum repository")
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if _is_root(candidate):
            return candidate
    raise WorkspaceNotFoundError(f"no practicum repository found at or above {current}")


def _is_root(path: Path) -> bool:
    return (path / "pixi.toml").is_file() and (path / "labs").is_dir()
