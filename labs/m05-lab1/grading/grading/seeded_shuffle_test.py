"""Grader: shuffle(cards, rng) must use the generator it is given."""

import random
import unittest

from deck.deck import new_deck, shuffle


class SeededShuffleTest(unittest.TestCase):
    def test_same_seed_same_order(self) -> None:
        cards = new_deck()
        first = shuffle(cards, random.Random(7))
        second = shuffle(cards, random.Random(7))
        self.assertEqual(first, second, "shuffle(cards, rng) should shuffle with rng")
        self.assertEqual(sorted(first), sorted(cards))

    def test_does_not_modify_its_input(self) -> None:
        cards = new_deck()
        shuffle(cards, random.Random(7))
        self.assertEqual(cards, new_deck())


if __name__ == "__main__":
    unittest.main()
