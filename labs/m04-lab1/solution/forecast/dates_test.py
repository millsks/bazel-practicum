"""pytest-style tests: plain functions and parametrize, no unittest classes."""

import pytest

from forecast.dates import next_month, weekday


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2026-11-09", "Monday"), ("2026-12-25", "Friday")],
)
def test_weekday(text, expected):
    assert weekday(text) == expected


def test_next_month_clamps_to_month_end():
    assert next_month("2026-01-31") == "2026-02-28"
