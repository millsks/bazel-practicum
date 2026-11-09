"""Formats a report. This test used to call a web service; it is a pure unit test now."""

import unittest

from textstats.stats import top_word, word_count


def report(text: str) -> str:
    return "%d words, most common: %s" % (word_count(text), top_word(text))


class ReportTest(unittest.TestCase):
    def test_report(self) -> None:
        self.assertEqual(report("to be or not to be"), "6 words, most common: to")


if __name__ == "__main__":
    unittest.main()
