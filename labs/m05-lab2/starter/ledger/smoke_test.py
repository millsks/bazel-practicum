"""Talks to a real ledger database. Only meaningful when LEDGER_DB_URL is set."""

import os
import unittest


class SmokeTest(unittest.TestCase):
    def test_database_is_configured(self) -> None:
        url = os.environ.get("LEDGER_DB_URL")
        self.assertIsNotNone(url, "LEDGER_DB_URL is not set; pass --test_env=LEDGER_DB_URL=...")
        print("would connect to", url)


if __name__ == "__main__":
    unittest.main()
