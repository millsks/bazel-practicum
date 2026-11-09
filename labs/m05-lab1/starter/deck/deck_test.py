import unittest

from deck.deck import new_deck, shuffle


class ShuffleTest(unittest.TestCase):
    def test_shuffle_keeps_every_card(self) -> None:
        cards = new_deck()
        self.assertEqual(sorted(shuffle(cards)), sorted(cards))

    def test_shuffle_is_fair(self) -> None:
        # Shuffle 20 times; the ace of spades should be on top about 5 times.
        cards = new_deck()
        on_top = sum(shuffle(cards)[0] == "ace of spades" for _ in range(20))
        self.assertIn(on_top, range(4, 7))


if __name__ == "__main__":
    unittest.main()
