"""Macros for the handbook's documentation."""

def markdown_toc(name, src, visibility = None):
    """Generates a table of contents for one Markdown file.

    Creates:
      <name>_gen  a genrule that runs //tools:toc on src, writing <name>.toc.md
      <name>      a filegroup holding just <name>.toc.md, with the given visibility

    Args:
      name: the name of the filegroup; the other target and the output start with it.
      src: the Markdown file to read.
      visibility: who may depend on <name>. The genrule stays private.
    """
    fail("TODO: write markdown_toc (see the docstring)")
