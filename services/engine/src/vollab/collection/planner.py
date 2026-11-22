"""Detecção de pendências da coleta (ADR-07, RF-DAD-02/05).

O que falta é calculado a partir do estado do banco, sem agendador: para cada pregão da
janela, o que ainda não tem um item concluído (`ok`, `vazio` ou falha permanente). Ordem dos
itens (PRD-NF-04): COTAHIST anual → COTAHIST diário → Selic e proventos → ativo-objeto →
opções. As opções de um pregão só são conhecidas depois do COTAHIST desse pregão.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from vollab.collection.params import CollectionParams
from vollab.db.models import (
    CollectionItem,
    DailyBar,
    ExchangeHoliday,
    OptionDailyStat,
    RiskFreeRate,
    Underlying,
)
from vollab.quant.calendar import last_n_business_days, previous_business_day
from vollab.settings import Settings

SAO_PAULO = ZoneInfo("America/Sao_Paulo")

PHASE_ANNUAL = 0
PHASE_DAILY = 1
PHASE_REFERENCE = 2
PHASE_UNDERLYING = 3
PHASE_OPTIONS = 4
NO_KEY = "-"


@dataclass(frozen=True, order=True)
class ItemSpec:
    phase: int
    source: str
    key: str
    trade_date: date
    underlying: str | None = None


def today_sao_paulo(settings: Settings) -> date:
    if settings.collection_today is not None:
        return settings.collection_today
    from datetime import datetime

    return datetime.now(tz=SAO_PAULO).date()


def load_holidays(session: Session) -> set[date]:
    return set(session.scalars(select(ExchangeHoliday.day)))


def reference_date(today: date, holidays: set[date]) -> date:
    """Último pregão a coletar: D-1 (RF-DAD-01)."""
    return previous_business_day(today, holidays)


def done_keys(session: Session, *, since: date) -> set[tuple[str, str, date]]:
    """Itens já resolvidos em qualquer execução: ok, vazio ou falha permanente (404)."""
    stmt = select(CollectionItem.source, CollectionItem.key, CollectionItem.trade_date).where(
        CollectionItem.trade_date >= since,
        or_(
            CollectionItem.status.in_(("ok", "empty")),
            and_(CollectionItem.status == "failed", CollectionItem.permanent.is_(True)),
        ),
    )
    return {(s, k, d) for s, k, d in session.execute(stmt)}


def active_underlyings(session: Session, *, user_id: uuid.UUID) -> list[Underlying]:
    return list(
        session.scalars(
            select(Underlying)
            .where(Underlying.user_id == user_id, Underlying.active.is_(True))
            .order_by(Underlying.ticker)
        )
    )


_ELIGIBLE_SQL = text(
    """
    WITH cand AS (
        SELECT s.underlying_isin AS isin, st.trade_date AS day, s.code, s.expiry, st.strike,
               st.trades_count, s.is_weekly
        FROM option_daily_stats st
        JOIN option_series s ON s.id = st.series_id
        WHERE st.trade_date = ANY(:days) AND s.underlying_isin = ANY(:isins) AND s.expiry > st.trade_date
    ),
    monthly AS (
        SELECT isin, day, expiry, dense_rank() OVER (PARTITION BY isin, day ORDER BY expiry) AS rk
        FROM (SELECT DISTINCT isin, day, expiry FROM cand WHERE NOT is_weekly) m
    ),
    horizon AS (
        SELECT isin, day, max(expiry) AS last_expiry FROM monthly WHERE rk <= :n_monthly GROUP BY isin, day
    )
    SELECT b.ticker, c.day, c.code
    FROM cand c
    JOIN horizon h ON h.isin = c.isin AND h.day = c.day
    JOIN daily_bars b ON b.isin = c.isin AND b.trade_date = c.day AND b.ticker = ANY(:tickers)
    LEFT JOIN monthly m ON m.isin = c.isin AND m.day = c.day AND m.expiry = c.expiry
    WHERE b.close > 0
      AND c.trades_count >= :min_trades
      AND c.strike / b.close BETWEEN :k_min AND :k_max
      AND (
            (NOT c.is_weekly AND m.rk <= :n_monthly)
         OR (c.is_weekly AND :weeklies AND c.expiry <= h.last_expiry)
      )
    ORDER BY c.day DESC, b.ticker, c.expiry, c.strike, c.code
    """
)


def option_items_for_days(
    session: Session, *, days: list[date], underlyings: list[Underlying], params: CollectionParams
) -> list[ItemSpec]:
    """Séries elegíveis dos pregões segundo o COTAHIST já gravado (RF-DAD-02, QA-06).

    Uma consulta só, com o filtro no banco (revisão de performance da Etapa 2: o N+1 com filtro
    em Python levava ~0,4 s por chamada de /collection/pending). A regra é a mesma de
    `eligibility.eligible_series`, conferida por teste de integração.
    """
    with_isin = [u for u in underlyings if u.isin]
    if not days or not with_isin:
        return []
    rules = params.liquidity
    rows = session.execute(
        _ELIGIBLE_SQL,
        {
            "days": days,
            "isins": [u.isin for u in with_isin],
            "tickers": [u.ticker for u in with_isin],
            "n_monthly": rules.monthly_expiries,
            "min_trades": rules.min_trades,
            "k_min": rules.moneyness_min,
            "k_max": rules.moneyness_max,
            "weeklies": rules.include_weeklies,
        },
    ).all()
    return [ItemSpec(PHASE_OPTIONS, "b3_trades", code, day, ticker) for ticker, day, code in rows]


def option_items_for_day(
    session: Session, *, day: date, underlyings: list[Underlying], params: CollectionParams
) -> list[ItemSpec]:
    return option_items_for_days(session, days=[day], underlyings=underlyings, params=params)


@dataclass(frozen=True)
class Plan:
    reference_date: date
    intraday_days: list[date]
    bar_days: list[date]
    items: list[ItemSpec]
    # Pregões da janela cujo COTAHIST ainda não foi gravado: as opções deles só serão conhecidas depois.
    days_without_cotahist: list[date]


def build_plan(session: Session, *, user_id: uuid.UUID, today: date, params: CollectionParams) -> Plan:
    holidays = load_holidays(session)
    ref = reference_date(today, holidays)
    intraday = last_n_business_days(ref, params.window.intraday_bd, holidays)
    bar_days = last_n_business_days(ref, params.window.daily_bars_bd, holidays)
    underlyings = active_underlyings(session, user_id=user_id)
    tickers = [u.ticker for u in underlyings]
    done = done_keys(session, since=min(bar_days[0], date(bar_days[0].year, 1, 1)))
    items: list[ItemSpec] = []

    def add(spec: ItemSpec) -> None:
        if (spec.source, spec.key, spec.trade_date) not in done:
            items.append(spec)

    # OHLC oficial fora da janela intradiária: COTAHIST anual (1 requisição por ano).
    have_bars: dict[str, set[date]] = defaultdict(set)
    if tickers:
        for ticker, day in session.execute(
            select(DailyBar.ticker, DailyBar.trade_date).where(
                DailyBar.ticker.in_(tickers), DailyBar.trade_date >= bar_days[0]
            )
        ):
            have_bars[ticker].add(day)
    intraday_set = set(intraday)
    missing_by_year: dict[int, date] = {}
    for day in bar_days:
        if day in intraday_set:
            continue
        if any(day not in have_bars[t] for t in tickers):
            missing_by_year[day.year] = max(day, missing_by_year.get(day.year, day))
    for year, last_missing in sorted(missing_by_year.items()):
        # A chave inclui o último pregão faltante: um anual que já cobriu esse pregão não é baixado de novo.
        add(ItemSpec(PHASE_ANNUAL, "b3_cotahist_annual", str(year), last_missing))

    for day in intraday:
        add(ItemSpec(PHASE_DAILY, "b3_cotahist_daily", NO_KEY, day))

    have_rates = set(session.scalars(select(RiskFreeRate.day).where(RiskFreeRate.day >= bar_days[0])))
    if any(d not in have_rates for d in bar_days):
        add(ItemSpec(PHASE_REFERENCE, "bcb_selic", "1178", ref))
    for ticker in tickers:
        add(ItemSpec(PHASE_REFERENCE, "yahoo_dividends", ticker, ref, ticker))

    for day in intraday:
        for ticker in tickers:
            add(ItemSpec(PHASE_UNDERLYING, "b3_trades", ticker, day, ticker))

    days_with_stats = set(
        session.scalars(
            select(OptionDailyStat.trade_date)
            .where(OptionDailyStat.trade_date.in_(intraday))
            .group_by(OptionDailyStat.trade_date)
        )
    )
    days_without: list[date] = []
    for spec in option_items_for_days(
        session, days=sorted(days_with_stats), underlyings=underlyings, params=params
    ):
        add(spec)
    for day in intraday:
        if day not in days_with_stats and ("b3_cotahist_daily", NO_KEY, day) not in done:
            days_without.append(day)
    return Plan(ref, intraday, bar_days, items, days_without)


def selic_range(plan: Plan) -> tuple[date, date]:
    return plan.bar_days[0], plan.reference_date


def count_requests(items: list[ItemSpec]) -> int:
    return len(items)


def has_any_collection(session: Session) -> bool:
    return bool(
        session.scalar(select(func.count()).select_from(CollectionItem).where(CollectionItem.status == "ok"))
    )
