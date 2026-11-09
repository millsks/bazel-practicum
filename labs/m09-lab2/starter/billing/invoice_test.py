import unittest

from billing.invoice import summary


class InvoiceTest(unittest.TestCase):
    def test_summary(self) -> None:
        self.assertEqual(summary([1000, 250]), "2 items, total $12.50")


if __name__ == "__main__":
    unittest.main()
