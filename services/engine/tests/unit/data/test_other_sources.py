"""Parsing do BCB (Selic), do Yahoo (proventos) e da lista de feriados, com fixtures reais."""

from datetime import date
from decimal import Decimal

import pytest

from tests.conftest import FIXTURES
from vollab.data.bcb import SgsParseError, parse_sgs
from vollab.data.holidays import seed_holidays
from vollab.data.yahoo import YahooParseError, parse_dividends
from vollab.quant.calendar import business_days


def test_selic_is_converted_from_percent_to_decimal() -> None:
    """PRD §5.1 / T-REF-06: o SGS envia percentual; o banco guarda decimal."""
    points = parse_sgs((FIXTURES / "bcb" / "sgs1178_2026-11.json").read_bytes())
    assert points[0].day == date(2026, 11, 3)
    assert all(p.rate == Decimal("0.1365") for p in points)
    # Finados (02/11) não tem valor: conferência cruzada do calendário.
    assert date(2026, 11, 2) not in {p.day for p in points}


@pytest.mark.parametrize("content", [b"{}", b"[{}]", b'[{"data":"31/02/2026","valor":"13.65"}]', b"x"])
def test_selic_malformed(content: bytes) -> None:
    with pytest.raises(SgsParseError):
        parse_sgs(content)


def test_yahoo_dividends_dates_match_strike_adjustment() -> None:
    """RS-02: data ex de PETR4 coincide com o ajuste de strike de 24/08/2026 (Etapa 0 §4, §8)."""
    points = parse_dividends((FIXTURES / "yahoo" / "PETR4.json").read_bytes(), expected_symbol="PETR4")
    by_day = {p.ex_date: p.amount for p in points}
    assert date(2026, 8, 24) in by_day
    # Valor do Yahoo diverge do ajuste oficial (1,19): por isso é gravado como estimado.
    assert by_day[date(2026, 8, 24)] == Decimal("1.348143")


def test_yahoo_rejects_other_symbol() -> None:
    with pytest.raises(YahooParseError):
        parse_dividends((FIXTURES / "yahoo" / "PETR4.json").read_bytes(), expected_symbol="VALE3")


def test_holidays_reproduce_b3_closures_2025_2026() -> None:
    """QA-02: dias úteis sem pregão de 2025–2026 (Etapa 0 §5)."""
    holidays = {h.day: h for h in seed_holidays()}
    closed_2025 = {
        date(2025, m, d)
        for m, d in [(1, 1), (3, 3), (3, 4), (4, 18), (4, 21), (5, 1), (6, 19), (11, 20), (12, 24), (12, 25)]
    } | {date(2025, 12, 31)}
    closed_2026 = {
        date(2026, m, d)
        for m, d in [
            (1, 1), (2, 16), (2, 17), (4, 3), (4, 21), (5, 1), (6, 4), (9, 7),
            (10, 12), (11, 2), (11, 20), (12, 24), (12, 25), (12, 31),
        ]
    }  # fmt: skip
    for year, expected in ((2025, closed_2025), (2026, closed_2026)):
        weekdays = {d for d in holidays if d.year == year and d.weekday() < 5}
        assert weekdays == expected, year
        assert all(holidays[d].confirmed for d in expected)
    # 25/01 e 09/07 (feriados de SP) têm pregão.
    assert date(2026, 1, 26) not in holidays
    assert date(2025, 7, 9) not in holidays


def test_holidays_2027_are_provisional() -> None:
    holidays = {h.day: h for h in seed_holidays()}
    expected = {
        date(2027, m, d)
        for m, d in [(1, 1), (2, 8), (2, 9), (3, 26), (4, 21), (5, 27), (9, 7), (10, 12), (11, 2), (11, 15)]
    } | {date(2027, 12, 24), date(2027, 12, 31)}
    weekdays = {d for d in holidays if d.year == 2027 and d.weekday() < 5}
    assert weekdays == expected
    assert not any(holidays[d].confirmed for d in expected)


def test_business_days_november_2026() -> None:
    holidays = {h.day for h in seed_holidays()}
    days = list(business_days(date(2026, 11, 1), date(2026, 11, 30), holidays))
    assert date(2026, 11, 2) not in days and date(2026, 11, 20) not in days
    assert len(days) == 19
