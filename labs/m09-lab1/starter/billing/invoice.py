"""Invoice totals. Only needs text formatting."""

from common.text import money, plural


def summary(prices_in_cents: list[int]) -> str:
    total = sum(prices_in_cents)
    return f"{plural(len(prices_in_cents), 'item')}, total {money(total)}"
