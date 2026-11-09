import os
import unittest
from pathlib import Path

from python.runfiles import runfiles

from ledger.ledger import export_csv, load_entries, total


class LedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        r = runfiles.Create()
        self.entries = load_entries(r.Rlocation("_main/ledger/testdata/entries.json"))

    def test_total(self) -> None:
        self.assertEqual(total(self.entries), 38.25)

    def test_export_csv(self) -> None:
        out = Path(os.environ["TEST_TMPDIR"]) / "export.csv"
        export_csv(self.entries, out)
        lines = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "date,amount")
        self.assertEqual(len(lines), 4)


if __name__ == "__main__":
    unittest.main()
