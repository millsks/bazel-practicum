"""Reads the price list that ships next to this module."""

import csv
from pathlib import Path

# Look for prices.csv next to this file. Under `bazel test` this file lives in the
# test's runfiles tree, so prices.csv is only there if a target declares it.
PRICES = Path(__file__).parent / "prices.csv"


def load_prices() -> dict[str, int]:
    """Return {item: price in cents} from prices.csv."""
    with PRICES.open(newline="") as f:
        return {row["item"]: int(row["price_cents"]) for row in csv.DictReader(f)}


def total(items: list[str]) -> int:
    """Return the total price, in cents, of the given items."""
    prices = load_prices()
    return sum(prices[item] for item in items)
