"""Small date helpers for the weather service."""

from dateutil.parser import isoparse
from dateutil.relativedelta import relativedelta


def weekday(text: str) -> str:
    """Return the weekday name of an ISO 8601 date, such as "Monday"."""
    return isoparse(text).strftime("%A")


def next_month(text: str) -> str:
    """Return the same day one month later, clamped to the month's end."""
    return (isoparse(text) + relativedelta(months=1)).date().isoformat()
