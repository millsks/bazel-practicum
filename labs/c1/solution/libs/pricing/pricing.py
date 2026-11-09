"""Price an order against the product catalog.

An order maps SKUs to quantities, for example {"WIDGET": 2, "GADGET": 1}.
Every amount is a whole number of cents: no floats anywhere near money.
"""

from tabulate import tabulate

from data.catalog import PRODUCTS


def parse_order(items: list[str]) -> dict[str, int]:
    """Turn ["WIDGET=2", "GADGET"] into {"WIDGET": 2, "GADGET": 1}."""
    order: dict[str, int] = {}
    for item in items:
        sku, _, qty = item.partition("=")
        sku = sku.strip().upper()
        if sku not in PRODUCTS:
            raise ValueError(f"unknown SKU {sku!r}; known: {', '.join(sorted(PRODUCTS))}")
        order[sku] = order.get(sku, 0) + int(qty or "1")
    return order


def line_items(order: dict[str, int]) -> list[tuple[str, int, int, int]]:
    """(name, quantity, unit price, line total) for each SKU, sorted by SKU."""
    lines = []
    for sku in sorted(order):
        name, unit = PRODUCTS[sku]
        lines.append((name, order[sku], unit, unit * order[sku]))
    return lines


def subtotal(order: dict[str, int]) -> int:
    """The order's total before tax, in cents."""
    return sum(total for _, _, _, total in line_items(order))


def tax(cents: int, percent: int) -> int:
    """Tax on an amount, rounded half up to a whole cent."""
    return (cents * percent + 50) // 100


def table(rows: list[tuple[str, str, str, str]]) -> str:
    """Lay out (item, qty, unit, total) rows as a plain-text table."""
    return tabulate(
        rows,
        headers=["item", "qty", "unit", "total"],
        tablefmt="simple",
        colalign=("left", "right", "right", "right"),
        disable_numparse=True,
    )
