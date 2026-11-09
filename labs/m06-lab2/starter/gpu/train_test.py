import unittest


class TrainTest(unittest.TestCase):
    def test_needs_a_gpu(self) -> None:
        self.fail("no GPU on this machine: this test should never run on a CPU-only platform")


if __name__ == "__main__":
    unittest.main()
