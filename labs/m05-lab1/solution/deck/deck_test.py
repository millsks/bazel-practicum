import random
import unittest

from deck.deck import new_deck, shuffle


class ShuffleTest(unittest.TestCase):
    def test_shuffle_keeps_every_card(self) -> None:
        cards = new_deck()
        self.assertEqual(sorted(shuffle(cards)), sorted(cards))

    def test_shuffle_is_fair(self) -> None:
        # A seeded generator makes the result the same on every run, while
        # 4000 shuffles still say something about fairness (about 1000 on top).
        rng = random.Random(1234)
        cards = new_deck()
        on_top = sum(shuffle(cards, rng)[0] == "ace of spades" for _ in range(4000))
        self.assertIn(on_top, range(900, 1101))


if __name__ == "__main__":
    unittest.main()
