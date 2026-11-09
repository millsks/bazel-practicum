"""Word counting helpers."""


def word_count(text: str) -> int:
    """Number of whitespace-separated words in ``text``."""
    return len(text.split())


def unique_words(text: str) -> int:
    """Number of distinct words, ignoring case."""
    return len({word.lower() for word in text.split()})
