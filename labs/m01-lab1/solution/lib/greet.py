"""Formats the greeting that //app:cli prints."""


def greet(name: str) -> str:
    """Return the CLI's greeting for ``name``."""
    return f"Hello, {name}! Built by Bazel."
