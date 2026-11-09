"""Small text statistics."""


def word_count(text: str) -> int:
    """Return the number of whitespace-separated words in ``text``."""
    return len(text.split())


def top_word(text: str) -> str:
    """Return the most frequent word (lowercased); ties go to the word seen first."""
    counts: dict[str, int] = {}
    for word in text.lower().split():
        counts[word] = counts.get(word, 0) + 1
    return max(counts, key=lambda w: counts[w])
