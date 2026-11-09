"""Pure functions over the catalog: no file access, easy to test."""


def total_value(catalog: dict[str, dict[str, float]]) -> float:
    """Sum price * count over every item."""
    return sum(item["price"] * item["count"] for item in catalog.values())


def summary_line(catalog: dict[str, dict[str, float]]) -> str:
    """One line such as '3 items, total value 45.50'."""
    return f"{len(catalog)} items, total value {total_value(catalog):.2f}"
