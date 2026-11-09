"""Grader's test: textstats is importable by its package name from another Bazel package."""

import unittest

import textstats
from textstats.counting import unique_words


class ApiTest(unittest.TestCase):
    def test_public_names(self) -> None:
        self.assertEqual(textstats.word_count("a b c"), 3)
        self.assertEqual(unique_words("a A b"), 2)


if __name__ == "__main__":
    unittest.main()
