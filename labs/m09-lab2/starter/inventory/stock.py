"""Stock levels. Only needs text formatting."""

from common.text import plural


def describe(name: str, count: int) -> str:
    return f"{name}: {plural(count, 'unit')} left"
