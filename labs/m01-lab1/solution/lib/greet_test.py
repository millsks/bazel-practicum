"""Tests for lib.greet, run by `bazel test //lib:greet_test`."""

import unittest

from lib.greet import greet


class GreetTest(unittest.TestCase):
    def test_greets_by_name(self) -> None:
        self.assertEqual(greet("Ada"), "Hello, Ada! Built by Bazel.")


if __name__ == "__main__":
    unittest.main()
