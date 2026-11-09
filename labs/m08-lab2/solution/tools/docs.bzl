"""Macros for the handbook's documentation."""

def _toc_name(name):
    """The output file for markdown_toc(name = ...). Private: BUILD files cannot load it."""
    return name + ".toc.md"

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
    out = _toc_name(name)
    native.genrule(
        name = name + "_gen",
        srcs = [src],
        outs = [out],
        tools = ["//tools:toc"],
        cmd = "$(location //tools:toc) $< $@",
        visibility = ["//visibility:private"],
    )
    native.filegroup(
        name = name,
        srcs = [":" + out],
        visibility = visibility,
    )
