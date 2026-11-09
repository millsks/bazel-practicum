"""Tests for hello.greeting, run by `bazel test //hello:greeting_test`."""

import unittest

from hello.greeting import greeting


class GreetingTest(unittest.TestCase):
    def test_greets_by_name(self) -> None:
        self.assertEqual(greeting("Bazel"), "Hello, Bazel!")


if __name__ == "__main__":
    unittest.main()
