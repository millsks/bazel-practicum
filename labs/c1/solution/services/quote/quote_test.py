"""Tests of the quote service, including the Go formatter it runs."""

import unittest

from services.quote import quote


class QuoteTest(unittest.TestCase):
    def test_region_comes_from_the_runfiles(self) -> None:
        self.assertIn(quote.load_region()["region"], ("us", "eu"))

    def test_go_formatter_runs(self) -> None:
        self.assertEqual(quote.format_money("USD", [123456]), ["$1,234.56"])

    def test_render_totals_the_order(self) -> None:
        text = quote.render(["WIDGET=2", "GADGET"])
        self.assertIn("Widget", text)
        self.assertTrue(text.splitlines()[-1].startswith("total"))


if __name__ == "__main__":
    unittest.main()
