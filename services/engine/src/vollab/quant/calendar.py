"""Calendário de pregões (RN-PRC-05). Puro: recebe o conjunto de feriados, não faz I/O."""

from collections.abc import Iterator, Set
from datetime import date, timedelta

_ONE_DAY = timedelta(days=1)


def is_business_day(day: date, holidays: Set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def business_days(start: date, end: date, holidays: Set[date]) -> Iterator[date]:
    """Pregões em [start, end], em ordem crescente."""
    day = start
    while day <= end:
        if is_business_day(day, holidays):
            yield day
        day += _ONE_DAY


def previous_business_day(day: date, holidays: Set[date]) -> date:
    """Último pregão estritamente anterior a `day`."""
    day -= _ONE_DAY
    while not is_business_day(day, holidays):
        day -= _ONE_DAY
    return day


def last_n_business_days(end: date, n: int, holidays: Set[date]) -> list[date]:
    """Os `n` últimos pregões até `end` (inclusive), em ordem crescente."""
    if n <= 0:
        return []
    out: list[date] = []
    day = end if is_business_day(end, holidays) else previous_business_day(end, holidays)
    while len(out) < n:
        out.append(day)
        day = previous_business_day(day, holidays)
    out.reverse()
    return out


def count_business_days(start: date, end: date, holidays: Set[date]) -> int:
    """Pregões em (start, end]: convenção de prazo em dias úteis (`_bd`)."""
    if end <= start:
        return 0
    return sum(1 for _ in business_days(start + _ONE_DAY, end, holidays))
