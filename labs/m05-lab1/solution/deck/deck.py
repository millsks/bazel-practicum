"""A tiny deck of cards."""

import random

SUITS = ["clubs", "diamonds", "hearts", "spades"]


def new_deck() -> list[str]:
    """Return the four aces, in a fixed order."""
    return [f"ace of {suit}" for suit in SUITS]


def shuffle(cards: list[str], rng: random.Random | None = None) -> list[str]:
    """Return a shuffled copy of cards, using rng if one is given."""
    out = list(cards)
    (rng or random.Random()).shuffle(out)
    return out
