import unittest
from pathlib import Path

from ledger.ledger import export_csv, load_entries, total


class LedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = load_entries("testdata/entries.json")

    def test_total(self) -> None:
        self.assertEqual(total(self.entries), 38.25)

    def test_export_csv(self) -> None:
        out = Path(__file__).parent / "export.csv"
        export_csv(self.entries, out)
        lines = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "date,amount")
        self.assertEqual(len(lines), 4)


if __name__ == "__main__":
    unittest.main()
