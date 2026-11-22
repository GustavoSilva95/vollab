"""Detecção de pendências da coleta (ADR-07, RF-DAD-02/05).

O que falta é calculado a partir do estado do banco, sem agendador: para cada pregão da
janela, o que ainda não tem um item concluído (`ok`, `vazio` ou falha permanente). Ordem dos
itens (PRD-NF-04): COTAHIST anual → COTAHIST diário → Selic e proventos → ativo-objeto →
opções. As opções de um pregão só são conhecidas depois do COTAHIST desse pregão.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from vollab.collection.eligibility import SeriesDay, eligible_series
from vollab.collection.params import CollectionParams
from vollab.db.models import (
    CollectionItem,
    DailyBar,
    ExchangeHoliday,
    OptionDailyStat,
    OptionSeries,
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


def active_underlyings(session: Session) -> list[Underlying]:
    return list(
        session.scalars(select(Underlying).where(Underlying.active.is_(True)).order_by(Underlying.ticker))
    )


def option_items_for_day(
    session: Session, *, day: date, underlyings: list[Underlying], params: CollectionParams
) -> list[ItemSpec]:
    """Séries elegíveis do pregão segundo o COTAHIST já gravado (RF-DAD-02)."""
    by_isin = {u.isin: u.ticker for u in underlyings if u.isin}
    if not by_isin:
        return []
    spots = dict(
        session.execute(
            select(DailyBar.ticker, DailyBar.close).where(
                DailyBar.trade_date == day, DailyBar.ticker.in_(list(by_isin.values()))
            )
        ).all()
    )
    rows = session.execute(
        select(
            OptionSeries.underlying_isin,
            OptionSeries.code,
            OptionSeries.expiry,
            OptionDailyStat.strike,
            OptionDailyStat.trades_count,
            OptionSeries.is_weekly,
        )
        .join(OptionDailyStat, OptionDailyStat.series_id == OptionSeries.id)
        .where(OptionDailyStat.trade_date == day, OptionSeries.underlying_isin.in_(list(by_isin)))
    )
    candidates: dict[str, list[SeriesDay]] = defaultdict(list)
    for isin, code, expiry, strike, count, weekly in rows:
        candidates[isin].append(SeriesDay(code, expiry, strike, count, weekly))
    specs: list[ItemSpec] = []
    for isin, series in candidates.items():
        ticker = by_isin[isin]
        spot = spots.get(ticker)
        if spot is None:
            continue
        for s in eligible_series(series, spot=Decimal(spot), trade_date=day, rules=params.liquidity):
            specs.append(ItemSpec(PHASE_OPTIONS, "b3_trades", s.code, day, ticker))
    return specs


@dataclass(frozen=True)
class Plan:
    reference_date: date
    intraday_days: list[date]
    bar_days: list[date]
    items: list[ItemSpec]
    # Pregões da janela cujo COTAHIST ainda não foi gravado: as opções deles só serão conhecidas depois.
    days_without_cotahist: list[date]


def build_plan(session: Session, *, today: date, params: CollectionParams) -> Plan:
    holidays = load_holidays(session)
    ref = reference_date(today, holidays)
    intraday = last_n_business_days(ref, params.window.intraday_bd, holidays)
    bar_days = last_n_business_days(ref, params.window.daily_bars_bd, holidays)
    underlyings = active_underlyings(session)
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
    for day in intraday:
        if day in days_with_stats:
            for spec in option_items_for_day(session, day=day, underlyings=underlyings, params=params):
                add(spec)
        elif (("b3_cotahist_daily", NO_KEY, day)) not in done:
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
