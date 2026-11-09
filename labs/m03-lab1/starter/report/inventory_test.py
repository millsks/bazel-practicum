"""Unit tests for report.inventory (no data files needed)."""

import unittest

from report.inventory import summary_line, total_value

SAMPLE = {"tea": {"price": 2.0, "count": 3}, "jam": {"price": 4.5, "count": 1}}


class InventoryTest(unittest.TestCase):
    def test_total_value(self) -> None:
        self.assertAlmostEqual(total_value(SAMPLE), 10.5)

    def test_summary_line(self) -> None:
        self.assertEqual(summary_line(SAMPLE), "2 items, total value 10.50")


if __name__ == "__main__":
    unittest.main()
