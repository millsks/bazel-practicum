"""A tiny deck of cards."""

import random

SUITS = ["clubs", "diamonds", "hearts", "spades"]


def new_deck() -> list[str]:
    """Return the four aces, in a fixed order."""
    return [f"ace of {suit}" for suit in SUITS]


def shuffle(cards: list[str]) -> list[str]:
    """Return a shuffled copy of cards."""
    out = list(cards)
    random.shuffle(out)
    return out
