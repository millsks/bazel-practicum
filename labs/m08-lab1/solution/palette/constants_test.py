"""Tests for the generated palette.constants module."""

import unittest

from palette import constants


class ConstantsTest(unittest.TestCase):
    def test_primary_colors(self) -> None:
        self.assertEqual(constants.RED, "#ff0000")
        self.assertEqual(constants.BLUE, "#0000ff")

    def test_teal_was_added(self) -> None:
        self.assertEqual(constants.TEAL, "#008080")


if __name__ == "__main__":
    unittest.main()
