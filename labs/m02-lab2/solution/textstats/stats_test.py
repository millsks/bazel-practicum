"""Unit tests for textstats.stats."""

import unittest

from textstats.stats import top_word, word_count


class StatsTest(unittest.TestCase):
    def test_word_count(self) -> None:
        self.assertEqual(word_count("the quick brown fox"), 4)

    def test_top_word(self) -> None:
        self.assertEqual(top_word("a b A c a"), "a")


if __name__ == "__main__":
    unittest.main()
