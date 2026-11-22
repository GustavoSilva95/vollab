"""Leituras da coleta para a API: pendências, progresso e relatório de lacunas (RF-DAD-06)."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from vollab.collection.params import CollectionParams, params_from_config
from vollab.collection.planner import (
    PHASE_OPTIONS,
    Plan,
    active_underlyings,
    build_plan,
    load_holidays,
    reference_date,
)
from vollab.db.config_store import current_config_version
from vollab.db.models import CollectionItem, CollectionRun, DailyBar
from vollab.quant.calendar import last_n_business_days

# Rótulo de cada grupo de itens, como aparece na interface.
GROUPS = ("cotahist_annual", "cotahist_daily", "selic", "dividends", "underlying_trades", "option_trades")


def item_group(source: str, phase: int) -> str:
    return {
        "b3_cotahist_annual": "cotahist_annual",
        "b3_cotahist_daily": "cotahist_daily",
        "bcb_selic": "selic",
        "yahoo_dividends": "dividends",
    }.get(source, "option_trades" if phase == PHASE_OPTIONS else "underlying_trades")


def current_params(session: Session, *, user_id: uuid.UUID) -> CollectionParams:
    version = current_config_version(session, user_id=user_id)
    if version is None or "collection" not in version.params:
        return CollectionParams()
    return params_from_config(version)


# --- Pendências ---------------------------------------------------------------------------


@dataclass
class Pending:
    plan: Plan
    counts: dict[str, int]
    pending_days: list[date]
    is_initial_load: bool


def pending(session: Session, *, user_id: uuid.UUID, today: date) -> Pending:
    plan = build_plan(session, today=today, params=current_params(session, user_id=user_id))
    counts = dict.fromkeys(GROUPS, 0)
    days: set[date] = set()
    for spec in plan.items:
        counts[item_group(spec.source, spec.phase)] += 1
        if spec.source != "b3_cotahist_annual":
            days.add(spec.trade_date)
    finished = session.scalar(
        select(func.count())
        .select_from(CollectionRun)
        .where(CollectionRun.user_id == user_id, CollectionRun.status.in_(("succeeded", "partial")))
    )
    return Pending(plan, counts, sorted(days), is_initial_load=not finished)


def latest_runs(session: Session, *, user_id: uuid.UUID) -> tuple[CollectionRun | None, CollectionRun | None]:
    """(ativa, última encerrada)."""
    runs = session.scalars(
        select(CollectionRun)
        .where(CollectionRun.user_id == user_id)
        .order_by(CollectionRun.id.desc())
        .limit(5)
    ).all()
    active = next((r for r in runs if r.status in ("queued", "running")), None)
    last = next((r for r in runs if r.status not in ("queued", "running")), None)
    return active, last


def last_collection_at(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(CollectionRun.finished_at)).where(CollectionRun.status.in_(("succeeded", "partial")))
    )


# --- Progresso ----------------------------------------------------------------------------


@dataclass
class GroupProgress:
    group: str
    total: int = 0
    pending: int = 0
    ok: int = 0
    empty: int = 0
    failed: int = 0


@dataclass
class Progress:
    run: CollectionRun
    groups: list[GroupProgress]
    current: CollectionItem | None
    recent_failures: list[CollectionItem] = field(default_factory=list)

    @property
    def totals(self) -> GroupProgress:
        total = GroupProgress("total")
        for g in self.groups:
            total.total += g.total
            total.pending += g.pending
            total.ok += g.ok
            total.empty += g.empty
            total.failed += g.failed
        return total


def progress(session: Session, run: CollectionRun) -> Progress:
    rows = session.execute(
        select(CollectionItem.source, CollectionItem.phase, CollectionItem.status, func.count())
        .where(CollectionItem.run_id == run.id)
        .group_by(CollectionItem.source, CollectionItem.phase, CollectionItem.status)
    ).all()
    groups = {g: GroupProgress(g) for g in GROUPS}
    for source, phase, status, count in rows:
        g = groups[item_group(source, phase)]
        g.total += count
        setattr(g, status, getattr(g, status) + count)
    current = None
    if run.status in ("queued", "running"):
        current = session.scalar(
            select(CollectionItem)
            .where(CollectionItem.run_id == run.id, CollectionItem.status == "pending")
            .order_by(CollectionItem.phase, CollectionItem.trade_date.desc(), CollectionItem.id)
            .limit(1)
        )
    failures = session.scalars(
        select(CollectionItem)
        .where(CollectionItem.run_id == run.id, CollectionItem.status == "failed")
        .order_by(CollectionItem.updated_at.desc(), CollectionItem.id.desc())
        .limit(20)
    ).all()
    return Progress(run, list(groups.values()), current, list(failures))


# --- Relatório de lacunas -----------------------------------------------------------------


@dataclass(frozen=True)
class Gap:
    underlying: str | None
    trade_date: date
    kind: str
    detail: str
    count: int = 1


@dataclass
class GapReport:
    reference_date: date
    bars_start: date
    intraday_start: date
    gaps: list[Gap]
    failures: list[CollectionItem]


def gaps(session: Session, *, user_id: uuid.UUID, today: date) -> GapReport:
    """Falhas e lacunas por ativo e data na janela vigente (RF-DAD-06, RN-DAD-01, QA-02).

    Considera o estado mais recente de cada item (a última tentativa, em qualquer execução).
    """
    params = current_params(session, user_id=user_id)
    holidays = load_holidays(session)
    ref = reference_date(today, holidays)
    bar_days = last_n_business_days(ref, params.window.daily_bars_bd, holidays)
    intraday = last_n_business_days(ref, params.window.intraday_bd, holidays)
    tickers = [u.ticker for u in active_underlyings(session)]
    out: list[Gap] = []

    bars = {
        (t, d): (check, diff)
        for t, d, check, diff in session.execute(
            select(DailyBar.ticker, DailyBar.trade_date, DailyBar.r4_check, DailyBar.r4_diff).where(
                DailyBar.ticker.in_(tickers), DailyBar.trade_date >= bar_days[0]
            )
        ).all()
    }
    for day in bar_days:
        for t in tickers:
            bar = bars.get((t, day))
            if bar is None:
                out.append(Gap(t, day, "missing_bar", "Sem OHLC oficial (COTAHIST) neste pregão."))
            elif bar[0] == "diverged":
                out.append(
                    Gap(t, day, "r4_diverged", f"OHLC reconstruído pela R4 diverge do oficial em: {bar[1]}.")
                )

    latest = (
        select(CollectionItem)
        .where(CollectionItem.trade_date >= intraday[0], CollectionItem.status != "pending")
        .ext(distinct_on(CollectionItem.source, CollectionItem.key, CollectionItem.trade_date))
        .order_by(
            CollectionItem.source, CollectionItem.key, CollectionItem.trade_date, CollectionItem.id.desc()
        )
    )
    items = session.scalars(latest).all()
    failures = [i for i in items if i.status == "failed"]
    options_failed: dict[tuple[str | None, date], int] = {}
    for item in items:
        if item.source == "b3_trades" and item.phase != PHASE_OPTIONS and item.status == "empty":
            out.append(
                Gap(
                    item.underlying,
                    item.trade_date,
                    "calendar_alert",
                    "Pregão útil sem negócios do ativo-objeto: confira o calendário de feriados.",
                )
            )
        if item.status != "failed":
            continue
        if item.source == "b3_trades" and item.phase == PHASE_OPTIONS:
            key = (item.underlying, item.trade_date)
            options_failed[key] = options_failed.get(key, 0) + 1
        elif item.source == "b3_trades":
            out.append(
                Gap(item.underlying, item.trade_date, "underlying_trades_failed", item.error or "Falha.")
            )
        elif item.source == "b3_cotahist_daily":
            out.append(Gap(None, item.trade_date, "cotahist_failed", item.error or "Falha."))
    for (underlying, day), count in options_failed.items():
        out.append(Gap(underlying, day, "options_failed", "Séries de opção sem negócios coletados.", count))
    out.sort(key=lambda g: (g.trade_date, g.underlying or "", g.kind), reverse=True)
    failures.sort(key=lambda i: (i.trade_date, i.source, i.key), reverse=True)
    return GapReport(ref, bar_days[0], intraday[0], out, failures)
