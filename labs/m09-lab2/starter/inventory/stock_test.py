import unittest

from inventory.stock import describe


class StockTest(unittest.TestCase):
    def test_describe(self) -> None:
        self.assertEqual(describe("mug", 1), "mug: 1 unit left")


if __name__ == "__main__":
    unittest.main()
