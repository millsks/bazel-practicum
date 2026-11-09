import unittest

from common.text import money, plural


class TextTest(unittest.TestCase):
    def test_money(self) -> None:
        self.assertEqual(money(1250), "$12.50")
        self.assertEqual(money(7), "$0.07")

    def test_plural(self) -> None:
        self.assertEqual(plural(1, "item"), "1 item")
        self.assertEqual(plural(3, "item"), "3 items")


if __name__ == "__main__":
    unittest.main()
