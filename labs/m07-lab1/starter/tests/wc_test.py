"""End-to-end tests of the Go wc tool, written in Python."""

import os
import subprocess
import unittest

from python.runfiles import runfiles


def wc_path() -> str:
    """Find the wc binary in this test's runfiles."""
    rlocation = os.environ.get("WC_BIN")
    if not rlocation:
        raise AssertionError('WC_BIN is not set: add env = {"WC_BIN": "$(rlocationpath //tools/wc)"} to the py_test')
    path = runfiles.Create().Rlocation(rlocation)
    if path is None or not os.path.exists(path):
        raise AssertionError(f"{rlocation} is not in the runfiles: is //tools/wc in the test's data?")
    return path


def wc(*args: str, stdin: str = "") -> str:
    done = subprocess.run([wc_path(), *args], input=stdin, capture_output=True, text=True, check=True)
    return done.stdout


class WcTest(unittest.TestCase):
    def test_counts_arguments_as_lines(self) -> None:
        self.assertEqual(wc("to be or", "not to be"), "2 lines, 6 words\n")

    def test_counts_standard_input(self) -> None:
        self.assertEqual(wc(stdin="a b\nc\n"), "2 lines, 3 words\n")

    def test_empty_input(self) -> None:
        self.assertEqual(wc(), "0 lines, 0 words\n")


if __name__ == "__main__":
    unittest.main()
