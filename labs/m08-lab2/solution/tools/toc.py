"""Write a Markdown table of contents for a Markdown file.

Usage: toc.py INPUT.md OUTPUT.md

Every heading line ("#", "##", ...) becomes a bullet, indented by its level.
"""

import sys


def toc(markdown: str) -> str:
    """Return the table of contents for the given Markdown text."""
    lines = ["# Contents", ""]
    for line in markdown.splitlines():
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line.lstrip("#").strip()
            lines.append("  " * (level - 1) + "- " + title)
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> None:
    with open(argv[1]) as src, open(argv[2], "w") as out:
        out.write(toc(src.read()))


if __name__ == "__main__":
    main(sys.argv)
