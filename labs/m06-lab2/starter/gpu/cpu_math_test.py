import unittest


class CpuMathTest(unittest.TestCase):
    def test_sum(self) -> None:
        self.assertEqual(sum([1, 2, 3]), 6)


if __name__ == "__main__":
    unittest.main()
