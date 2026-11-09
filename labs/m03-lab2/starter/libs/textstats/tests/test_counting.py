"""Tests for textstats. Imports the package by its own name, as an installed package would be."""

import unittest

from textstats import unique_words, word_count


class CountingTest(unittest.TestCase):
    def test_word_count(self) -> None:
        self.assertEqual(word_count("the cat in the hat"), 5)

    def test_unique_words_ignores_case(self) -> None:
        self.assertEqual(unique_words("The cat in the hat"), 4)


if __name__ == "__main__":
    unittest.main()
