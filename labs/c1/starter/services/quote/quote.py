"""Build a customer quote: priced in Python, formatted by the Go tool.

Two things come from the runfiles, not from the source tree:

- data/regions/region.json, the region this binary was built for (Bazel picks
  us.json or eu.json at build time from --//config:region);
- the fmtcli Go binary, whose runfiles path arrives in the FMTCLI variable.
"""

import json
import os
import subprocess

from python.runfiles import runfiles

from libs.pricing import pricing

_RUNFILES = runfiles.Create()


def load_region() -> dict:
    """Read the region settings this binary was built with."""
    path = _RUNFILES.Rlocation("_main/data/regions/region.json")
    if path is None or not os.path.exists(path):
        raise RuntimeError("data/regions/region.json is not in the runfiles: add //data/regions:region to data")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmtcli_path() -> str:
    """Find the Go formatter in the runfiles."""
    rlocation = os.environ.get("FMTCLI")
    if not rlocation:
        raise RuntimeError('FMTCLI is not set: add env = {"FMTCLI": "$(rlocationpath //tools/fmtcli)"}')
    path = _RUNFILES.Rlocation(rlocation)
    if path is None or not os.path.exists(path):
        raise RuntimeError(f"{rlocation} is not in the runfiles: add //tools/fmtcli to data")
    return path


def format_money(currency: str, amounts: list[int]) -> list[str]:
    """Format many amounts with one run of the Go tool."""
    done = subprocess.run(
        [fmtcli_path(), currency, *(str(a) for a in amounts)],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.splitlines()


def render(items: list[str]) -> str:
    """The full quote for an order such as ["WIDGET=2", "GADGET"]."""
    region = load_region()
    currency, percent = region["currency"], region["tax_percent"]
    order = pricing.parse_order(items)
    lines = pricing.line_items(order)
    sub = pricing.subtotal(order)
    tax = pricing.tax(sub, percent)
    amounts = [cents for _, _, unit, total in lines for cents in (unit, total)] + [sub, tax, sub + tax]
    text = format_money(currency, amounts)
    rows = [(name, str(qty), text[2 * i], text[2 * i + 1]) for i, (name, qty, _, _) in enumerate(lines)]
    out = [f"Quote for region {region['region']} ({currency})", "", pricing.table(rows), ""]
    for label, amount in (("subtotal", text[-3]), (f"tax {percent}%", text[-2]), ("total", text[-1])):
        out.append(f"{label:<9} {amount}")
    return "\n".join(out)
