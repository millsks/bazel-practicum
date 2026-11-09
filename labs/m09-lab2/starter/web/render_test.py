import unittest

from common.render import render


class RenderTest(unittest.TestCase):
    def test_index(self) -> None:
        self.assertIn("<h1>Storefront</h1>", render("index.html", title="Storefront"))

    def test_receipt(self) -> None:
        self.assertIn("Total: $3.00", render("receipt.html", total="$3.00"))


if __name__ == "__main__":
    unittest.main()
