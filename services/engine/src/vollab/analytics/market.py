"""Leitura de dados de mercado já gravados, no formato que o motor puro (`quant`) espera.

Só leitura. Os agregados ficam no banco; negócios brutos só são lidos no worker (PRD-NF-06).
"""

import bisect
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from vollab.db.models import CorporateAction, DailyBar, ExchangeHoliday, RiskFreeRate, Underlying
from vollab.quant.calendar import business_days

# Prioridade entre fontes de proventos na mesma data ex (RS-02): o manual (usuário) prevalece, depois
# o oficial implícito no ajuste de strike da B3 e, por último, o histórico estimado do Yahoo.
DIVIDEND_SOURCE_PRIORITY = {"manual": 0, "b3_strike_adjustment": 1, "yahoo": 2}


def load_holidays(session: Session) -> frozenset[date]:
    return frozenset(session.scalars(select(ExchangeHoliday.day)))


def active_tickers(session: Session) -> list[str]:
    """Ativos ativos de qualquer usuário: dados de mercado são compartilhados (PRD §6)."""
    rows = session.scalars(select(Underlying.ticker).where(Underlying.active.is_(True)).distinct())
    return sorted(rows)


def underlying_isin(session: Session, ticker: str) -> str | None:
    return session.scalar(select(Underlying.isin).where(Underlying.ticker == ticker).limit(1))


@dataclass(frozen=True, slots=True)
class DividendInfo:
    amount: float
    source: str  # manual | b3_strike_adjustment | yahoo
    confirmed: bool


def load_dividends(session: Session, ticker: str) -> dict[date, DividendInfo]:
    """Provento por data ex, escolhido pela prioridade de fonte."""
    rows = session.execute(
        select(
            CorporateAction.ex_date, CorporateAction.amount, CorporateAction.source, CorporateAction.confirmed
        ).where(CorporateAction.ticker == ticker)
    )
    chosen: dict[date, tuple[int, DividendInfo]] = {}
    for ex_date, amount, source, confirmed in rows:
        rank = DIVIDEND_SOURCE_PRIORITY.get(source, 99)
        current = chosen.get(ex_date)
        if current is None or rank < current[0]:
            chosen[ex_date] = (rank, DividendInfo(float(amount), source, confirmed))
    return {d: info for d, (_, info) in chosen.items()}


@dataclass(frozen=True, slots=True)
class DailySeries:
    """OHLC oficial alinhado ao calendário de pregões (NaN = pregão sem barra)."""

    days: list[date]
    open: NDArray[np.float64]
    high: NDArray[np.float64]
    low: NDArray[np.float64]
    close: NDArray[np.float64]
    prev_close_adj: NDArray[np.float64]  # fechamento do pregão anterior menos o provento ex no dia
    dividend_on_day: NDArray[np.float64]  # provento com data ex no pregão (0 se nenhum)

    def index(self, day: date) -> int | None:
        i = bisect.bisect_left(self.days, day)
        return i if i < len(self.days) and self.days[i] == day else None


def load_daily_series(
    session: Session, ticker: str, holidays: frozenset[date], dividends: dict[date, DividendInfo]
) -> DailySeries | None:
    bars = session.execute(
        select(DailyBar.trade_date, DailyBar.open, DailyBar.high, DailyBar.low, DailyBar.close)
        .where(DailyBar.ticker == ticker)
        .order_by(DailyBar.trade_date)
    ).all()
    if not bars:
        return None
    by_day = {b[0]: b for b in bars}
    days = list(business_days(bars[0][0], bars[-1][0], holidays))
    n = len(days)
    o, h, lo, c = (np.full(n, np.nan) for _ in range(4))
    for i, d in enumerate(days):
        b = by_day.get(d)
        if b is not None:
            o[i], h[i], lo[i], c[i] = float(b[1]), float(b[2]), float(b[3]), float(b[4])
    div = np.array([dividends[d].amount if d in dividends else 0.0 for d in days])
    prev = np.concatenate([[np.nan], c[:-1]])
    # RN-VOL-07: na data ex, o fechamento anterior é reduzido pelo provento antes dos retornos.
    with np.errstate(invalid="ignore"):
        prev_adj = np.where(prev - div > 0, prev - div, np.nan)
    return DailySeries(days, o, h, lo, c, prev_adj, div)


class RateCurve:
    """Selic diária (decimal anual exponencial, base 252). Usa a última taxa até o dia."""

    def __init__(self, points: Iterable[tuple[date, float]]) -> None:
        ordered = sorted(points)
        self._days = [d for d, _ in ordered]
        self._rates = [r for _, r in ordered]

    def on(self, day: date) -> float | None:
        i = bisect.bisect_right(self._days, day) - 1
        return self._rates[i] if i >= 0 else None


def load_rates(session: Session) -> RateCurve:
    rows = session.execute(select(RiskFreeRate.day, RiskFreeRate.rate))
    return RateCurve((d, float(r)) for d, r in rows)


# Negócios válidos pela R4, com o horário em segundos desde a meia-noite de Brasília.
_TRADES_COLUMNS = (
    "SELECT EXTRACT(EPOCH FROM (traded_at AT TIME ZONE 'America/Sao_Paulo')::time)::float8 AS t, "
    "trade_id, price::float8 AS price, quantity, instrument, traded_at FROM trades WHERE r4_valid AND "
)
# Ativo-objeto: só as colunas usadas (horário, ID, preço, quantidade); ~20% mais rápido por pregão.
UNDERLYING_TRADES_SQL = (
    "SELECT EXTRACT(EPOCH FROM (traded_at AT TIME ZONE 'America/Sao_Paulo')::time)::float8 AS t, "
    "trade_id, price::float8 AS price, quantity FROM trades "
    "WHERE r4_valid AND instrument = :t AND reference_date = :d ORDER BY t, trade_id"
)
OPTION_TRADES_SQL = _TRADES_COLUMNS + "instrument = ANY(:codes) AND reference_date = :d ORDER BY t, trade_id"


UnderlyingTrades = tuple[NDArray[np.float64], NDArray[np.int64], NDArray[np.float64], NDArray[np.int64]]


def load_underlying_trades(session: Session, ticker: str, day: date) -> UnderlyingTrades:
    """Negócios válidos do ativo-objeto no pregão, ordenados por horário e identificador."""
    rows = session.execute(
        text(UNDERLYING_TRADES_SQL),
        {"t": ticker, "d": day},
    ).all()
    if not rows:
        empty_f = np.empty(0, dtype=np.float64)
        return empty_f, np.empty(0, dtype=np.int64), empty_f, np.empty(0, dtype=np.int64)
    t = np.fromiter((r[0] for r in rows), dtype=np.float64, count=len(rows))
    ids = np.fromiter((r[1] for r in rows), dtype=np.int64, count=len(rows))
    p = np.fromiter((r[2] for r in rows), dtype=np.float64, count=len(rows))
    q = np.fromiter((r[3] for r in rows), dtype=np.int64, count=len(rows))
    return t, ids, p, q


@dataclass(frozen=True, slots=True)
class IntradayVariance:
    """Variância intradiária por pregão alinhada à série diária (NaN = sem pregão completo)."""

    variance: NDArray[np.float64]
    incomplete: NDArray[np.bool_]
    first_index: int | None  # primeiro pregão com resumo intradiário (completo ou não)


def load_intraday_variance(session: Session, ticker: str, series: DailySeries) -> IntradayVariance:
    from vollab.db.models import IntradaySession  # import tardio: evita ciclo com os modelos de vol

    n = len(series.days)
    variance = np.full(n, np.nan)
    incomplete = np.zeros(n, dtype=bool)
    first: int | None = None
    rows = session.execute(
        select(IntradaySession.trade_date, IntradaySession.intraday_variance, IntradaySession.complete).where(
            IntradaySession.ticker == ticker
        )
    )
    for day, var, complete in rows:
        i = series.index(day)
        if i is None:
            continue
        first = i if first is None else min(first, i)
        if complete:
            variance[i] = var
        else:
            incomplete[i] = True
    return IntradayVariance(variance, incomplete, first)
