"""Tests for inventory.stock, run by `bazel test //inventory:stock_test`."""

import unittest

from inventory.stock import load_prices, total


class StockTest(unittest.TestCase):
    def test_reads_every_item(self) -> None:
        self.assertEqual(sorted(load_prices()), ["apple", "banana", "cherry"])

    def test_total(self) -> None:
        self.assertEqual(total(["apple", "apple", "cherry"]), 400)


if __name__ == "__main__":
    unittest.main()
