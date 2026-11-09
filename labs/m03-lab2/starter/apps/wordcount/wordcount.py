"""Prints word statistics for the words given on the command line."""

import sys

from textstats import unique_words, word_count

text = " ".join(sys.argv[1:])
print(f"{word_count(text)} words, {unique_words(text)} unique")
