"""Plain-text helpers with no dependencies."""


def money(cents: int) -> str:
    """Format an amount in cents as dollars: 1250 -> '$12.50'."""
    return f"${cents // 100}.{cents % 100:02d}"


def plural(n: int, word: str) -> str:
    """'1 item', '2 items'."""
    return f"{n} {word}" + ("" if n == 1 else "s")
