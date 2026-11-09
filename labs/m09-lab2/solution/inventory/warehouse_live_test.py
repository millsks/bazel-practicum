import os
import unittest


class WarehouseLiveTest(unittest.TestCase):
    def test_api_reachable(self) -> None:
        # Needs WAREHOUSE_URL from --test_env; fails everywhere else, on purpose.
        self.assertIn("WAREHOUSE_URL", os.environ)


if __name__ == "__main__":
    unittest.main()
