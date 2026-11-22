"""Pré-filtro das séries a coletar pelo COTAHIST do pregão (RF-DAD-02, QA-06). Puro, sem I/O."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from vollab.collection.params import LiquidityFilter


@dataclass(frozen=True, slots=True)
class SeriesDay:
    code: str
    expiry: date
    strike: Decimal
    trades_count: int
    is_weekly: bool


def eligible_series(
    candidates: Iterable[SeriesDay], *, spot: Decimal, trade_date: date, rules: LiquidityFilter
) -> list[SeriesDay]:
    """Séries elegíveis num pregão: os N próximos vencimentos mensais (semanais só se ligadas e
    dentro desses vencimentos), K/S na faixa e o mínimo de negócios no dia."""
    if spot <= 0:
        return []
    items = [c for c in candidates if c.expiry > trade_date]
    monthly = sorted({c.expiry for c in items if not c.is_weekly})[: rules.monthly_expiries]
    if not monthly:
        return []
    allowed_monthly = set(monthly)
    horizon = monthly[-1]
    out = []
    for c in items:
        if c.is_weekly:
            if not rules.include_weeklies or c.expiry > horizon:
                continue
        elif c.expiry not in allowed_monthly:
            continue
        moneyness = c.strike / spot
        if not rules.moneyness_min <= moneyness <= rules.moneyness_max:
            continue
        if c.trades_count < rules.min_trades:
            continue
        out.append(c)
    return sorted(out, key=lambda c: (c.expiry, c.strike, c.code))
