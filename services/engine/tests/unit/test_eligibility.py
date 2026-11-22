"""Pré-filtro de séries (RF-DAD-02, QA-06): ≥ 20 negócios, K/S 0,9–1,1, 2 mensais, sem semanais."""

from datetime import date
from decimal import Decimal

from vollab.collection.eligibility import SeriesDay, eligible_series
from vollab.collection.params import LiquidityFilter

DAY = date(2026, 11, 19)
DEC, JAN, FEB = date(2026, 12, 18), date(2027, 1, 15), date(2027, 2, 19)


def _s(code: str, expiry: date, strike: str, n: int = 50, weekly: bool = False) -> SeriesDay:
    return SeriesDay(code, expiry, Decimal(strike), n, weekly)


def test_default_filter() -> None:
    series = [
        _s("A", DEC, "42"),
        _s("B", JAN, "45"),
        _s("C", FEB, "42"),  # 3º vencimento mensal
        _s("D", DEC, "35"),  # K/S < 0,9
        _s("E", DEC, "42", n=19),  # liquidez
        _s("F", DEC, "42", n=20),  # no limite: entra
        _s("G", date(2026, 11, 27), "42", weekly=True),  # semanal desligada
        _s("H", DAY, "42"),  # vence hoje
    ]
    got = eligible_series(series, spot=Decimal("42"), trade_date=DAY, rules=LiquidityFilter())
    assert [s.code for s in got] == ["A", "F", "B"]


def test_moneyness_bounds_are_inclusive() -> None:
    series = [_s("LO", DEC, "36"), _s("HI", DEC, "44")]
    got = eligible_series(series, spot=Decimal("40"), trade_date=DAY, rules=LiquidityFilter())
    assert {s.code for s in got} == {"LO", "HI"}


def test_weeklies_when_enabled_stay_within_monthly_horizon() -> None:
    rules = LiquidityFilter(include_weeklies=True, monthly_expiries=1)
    series = [
        _s("M", DEC, "40"),
        _s("W", date(2026, 11, 27), "40", weekly=True),
        _s("W2", JAN, "40", weekly=True),
    ]
    got = eligible_series(series, spot=Decimal("40"), trade_date=DAY, rules=rules)
    assert [s.code for s in got] == ["W", "M"]


def test_no_spot_no_series() -> None:
    assert (
        eligible_series([_s("A", DEC, "40")], spot=Decimal(0), trade_date=DAY, rules=LiquidityFilter()) == []
    )
