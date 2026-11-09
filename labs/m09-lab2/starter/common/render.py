"""Fill in the HTML templates that live in //web:templates."""

from pathlib import Path

# The templates arrive in the runfiles tree through `data`; this file sits at
# <runfiles>/_main/common/render.py, so the workspace root is two levels up.
_ROOT = Path(__file__).parent.parent


def render(template: str, **values: str) -> str:
    text = (_ROOT / "web" / "templates" / template).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text
