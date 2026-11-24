"""Diário: lançamentos, marcação D-1 e atribuição (PRD 1.10 §5.9; BRD 1.7 RF-DIA-02..04, RS-06, CS-04).

- Lançamentos: validados pela reexecução do livro (`quant.journal`) e gravados imutáveis.
- Job `marks_recompute` (worker): para cada posição, marca cada pregão da entrada até o último pregão
  coletado (ou o encerramento) e refaz a atribuição. Dado derivado: apaga e regrava a posição inteira
  (idempotente). Enfileirado ao fim de cada `forecast_recompute` e a cada lançamento.

Marcação de cada perna: IV de referência (`observed`); sem ela, o fechamento do COTAHIST com a IV
extraída dele (`approximate`); sem os dois, a IV da marcação anterior com o S do dia (`stale`,
"desatualizado"); no primeiro pregão sem nenhum dos dois, o preço executado na entrada
(`approximate`). No vencimento e depois dele, o valor intrínseco do pregão do vencimento.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, cast

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, defer

from vollab.analytics.market import DividendInfo, load_dividends, load_holidays, load_rates
from vollab.analytics.params import (
    JournalParams,
    SimulationParams,
    SizingParams,
    VolParams,
    journal_params_from_config,
    simulation_params_from_config,
    sizing_params_from_config,
    vol_params_from_config,
)
from vollab.api.schemas.journal import (
    AttributionOut,
    Cs04Out,
    DeltaBandOut,
    EntryCreate,
    EntryOut,
    HoldingOut,
    MarkLegOut,
    MarkOut,
    TotalsOut,
)
from vollab.api.schemas.simulation import ManualInputOut, PositionOut, PositionSummary
from vollab.collection.params import ensure_config_version
from vollab.collection.planner import today_sao_paulo
from vollab.db.models import (
    FIXED_USER_ID,
    DailyBar,
    DailyMark,
    Job,
    JobStatus,
    ManualInput,
    OptionDailyQuote,
    OptionDailyStat,
    OptionSeries,
    PnlAttribution,
    Position,
    PositionEntry,
)
from vollab.jobs import queue
from vollab.jobs.handlers import register
from vollab.quant.attribution import (
    AttributionDay,
    DayMark,
    LegMark,
    LegQuote,
    attribute_life,
    delta_band_state,
    error_flag,
    mark_legs,
)
from vollab.quant.calendar import business_days, count_business_days, previous_business_day
from vollab.quant.journal import (
    EntryKind,
    Ledger,
    LedgerEntry,
    LedgerError,
    OptionInfo,
    PositionBook,
    holdings_until,
    pending_expiry,
    replay,
    replay_or_flag,
    validate_new,
)
from vollab.quant.pricing import BUSINESS_DAYS_PER_YEAR, IvStatus, continuous_rate, implied_vol
from vollab.settings import get_settings

log = structlog.get_logger("vollab.journal")
JOB_KIND = "marks_recompute"
# Primeiro inteiro do lock consultivo das operações (o segundo é o id; ids cabem em int4 no uso local).
ADVISORY_NS_POSITION = 7_001


# --- Livro a partir do banco ---------------------------------------------------------------------


def book_of(session: Session, ticker: str, entries: Sequence[PositionEntry]) -> PositionBook:
    """Pernas da operação = séries das entradas (`entry`/`roll`), com vencimento e estilo do cadastro."""
    ids = sorted({e.series_id for e in entries if e.series_id is not None})
    options: dict[str, OptionInfo] = {}
    for s in session.scalars(select(OptionSeries).where(OptionSeries.id.in_(ids))):
        options[s.code] = OptionInfo(s.code, s.id, s.option_type == "call", s.expiry, s.style == "european")
    return PositionBook(ticker, options)


def ledger_entry(e: PositionEntry) -> LedgerEntry:
    return LedgerEntry(
        id=e.id,
        kind=EntryKind(e.kind),
        instrument=e.instrument,
        quantity=e.quantity,
        price=e.price,
        fees=e.fees_brl,
        brokerage=e.brokerage_brl,
        executed_at=e.executed_at,
        series_id=e.series_id,
        linked_entry_id=e.linked_entry_id,
        strike_after=e.strike_after,
    )


def load_entries(session: Session, position_id: int) -> list[PositionEntry]:
    return list(
        session.scalars(
            select(PositionEntry).where(PositionEntry.position_id == position_id).order_by(PositionEntry.id)
        )
    )


# --- Fila --------------------------------------------------------------------------------------


def enqueue_marks(
    session: Session, *, user_id: uuid.UUID, position_ids: Sequence[int] | None, reason: str
) -> None:
    """Enfileira a marcação; não duplica um pedido igual (ou mais amplo) ainda na fila."""
    payload: dict[str, Any] = {"user_id": str(user_id), "reason": reason}
    if position_ids:
        payload["position_ids"] = sorted(set(position_ids))
    queued = session.scalars(
        select(Job).where(Job.kind == JOB_KIND, Job.user_id == user_id, Job.status == JobStatus.QUEUED)
    ).all()
    for job in queued:
        ids = job.payload.get("position_ids")
        if ids is None or (position_ids and set(position_ids) <= set(ids)):
            return
    queue.enqueue(session, user_id=user_id, kind=JOB_KIND, payload=payload, max_attempts=3)


@register(JOB_KIND)
def run_marks_job(session: Session, payload: dict[str, Any]) -> None:
    user_id = uuid.UUID(str(payload.get("user_id") or FIXED_USER_ID))
    ids = payload.get("position_ids")
    MarksComputer(session, user_id=user_id).run(list(ids) if isinstance(ids, list) else None)


# --- Marcação ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionMarks:
    marks: list[DayMark]
    attribution: list[AttributionDay]
    flags: list[bool]
    ledger: Ledger
    book: PositionBook
    # Por pregão e perna: insumos da reprecificação (tipo, strike efetivo, prazo, taxa, VP dos proventos).
    meta: list[dict[str, dict[str, Any]]]


class MarksComputer:
    def __init__(self, session: Session, *, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id
        version = ensure_config_version(session, user_id=user_id)
        session.commit()
        self.version_id = version.id
        self.vol: VolParams = vol_params_from_config(version)
        self.journal: JournalParams = journal_params_from_config(version)
        self.sim: SimulationParams = simulation_params_from_config(version)
        self.size: SizingParams = sizing_params_from_config(version)
        self.holidays = load_holidays(session)
        self.rates = load_rates(session)
        self.expected_as_of = previous_business_day(today_sao_paulo(get_settings()), self.holidays)
        self.engine_version = get_settings().engine_version
        self._strikes: dict[int, Decimal] = {}

    def run(self, position_ids: list[int] | None) -> None:
        """Sem `position_ids` (pós-coleta): só as abertas e as encerradas ainda não marcadas até o fim;
        uma encerrada já marcada não muda com um pregão novo (revisão de performance, I-2)."""
        stmt = (
            select(Position)
            .options(defer(Position.decision_snapshot))
            .where(Position.user_id == self.user_id)
        )
        if position_ids is not None:
            stmt = stmt.where(Position.id.in_(position_ids))
        positions = self.session.scalars(stmt.order_by(Position.id)).all()
        if position_ids is None:
            positions = self._needing_marks(positions)
        for p in positions:
            try:
                self.write(p)
            except (LedgerError, ValueError) as exc:
                # Uma operação com livro inconsistente ou sem como marcar não impede as outras nem
                # faz o job falhar e repetir tudo (revisão de performance, I-3).
                self.session.rollback()
                log.warning("marks.position_skipped", position_id=p.id, error=type(exc).__name__)
                continue
            self.session.commit()

    def _needing_marks(self, positions: Sequence[Position]) -> list[Position]:
        books = status_of(self.session, positions)
        last = dict(
            self.session.execute(
                select(DailyMark.position_id, func.max(DailyMark.trade_date))
                .where(DailyMark.position_id.in_([p.id for p in positions]))
                .group_by(DailyMark.position_id)
            ).all()
        )
        out = []
        for p in positions:
            ledger = books[p.id][0]
            if ledger.is_open or ledger.error:
                out.append(p)
                continue
            close_day = max((tx.day for tx in ledger.transactions), default=None)
            marked = last.get(p.id)
            if close_day is not None and (marked is None or marked < close_day):
                out.append(p)
        return out

    def write(self, position: Position) -> PositionMarks | None:
        result = self.compute(position)
        self.session.execute(delete(PnlAttribution).where(PnlAttribution.position_id == position.id))
        self.session.execute(delete(DailyMark).where(DailyMark.position_id == position.id))
        if result is None:
            return None
        for m, meta in zip(result.marks, result.meta, strict=True):
            d, g, v, th = m.greeks()
            opts = sum((Decimal(leg.quantity) * leg.price for leg in m.legs.values()), Decimal(0))
            self.session.add(
                DailyMark(
                    position_id=position.id,
                    trade_date=m.day,
                    spot=m.spot,
                    stock_qty=m.stock_qty,
                    options_value=opts,
                    stock_value=Decimal(m.stock_qty) * m.spot,
                    delta_shares=d,
                    gamma=g,
                    vega_per_point_brl=v,
                    theta_per_bd_brl=th,
                    stale=m.stale,
                    legs=[
                        {
                            "code": leg.code,
                            "series_id": result.book.options[leg.code].series_id,
                            "quantity": leg.quantity,
                            "price_brl": str(leg.price),
                            "iv": leg.iv,
                            "origin": leg.origin,
                            "delta": leg.delta,
                            "gamma": leg.gamma,
                            "vega_per_point": leg.vega_per_point,
                            "theta_per_bd": leg.theta_per_bd,
                        }
                        | meta.get(leg.code, {})
                        for leg in m.legs.values()
                    ],
                    config_version_id=self.version_id,
                    engine_version=self.engine_version,
                )
            )
        for a, flag in zip(result.attribution, result.flags, strict=True):
            self.session.add(
                PnlAttribution(
                    position_id=position.id,
                    trade_date=a.day,
                    delta_brl=a.delta,
                    gamma_brl=a.gamma,
                    theta_brl=a.theta,
                    vega_brl=a.vega,
                    market_brl=a.market,
                    residual_brl=a.residual,
                    execution_brl=a.execution,
                    stale=a.stale,
                    error_flag=flag,
                    config_version_id=self.version_id,
                    engine_version=self.engine_version,
                )
            )
        return result

    def compute(self, position: Position) -> PositionMarks | None:
        rows = load_entries(self.session, position.id)
        book = book_of(self.session, position.ticker, rows)
        ledger = replay([ledger_entry(e) for e in rows], book)
        if not ledger.transactions:
            return None
        first = min(tx.day for tx in ledger.transactions)
        last_bar = self.session.scalar(
            select(DailyBar.trade_date)
            .where(DailyBar.ticker == position.ticker, DailyBar.trade_date <= self.expected_as_of)
            .order_by(DailyBar.trade_date.desc())
            .limit(1)
        )
        if last_bar is None or last_bar < first:
            return None
        end = last_bar
        if not ledger.is_open:
            close_day = max(tx.day for tx in ledger.transactions)
            end = min(end, max(close_day, first))
            # Encerramento num dia sem pregão: marca até o pregão seguinte, se já houver.
            if not any(True for _ in business_days(close_day, close_day, self.holidays)):
                nxt = [d for d in business_days(close_day, last_bar, self.holidays)]
                end = nxt[0] if nxt else last_bar
        bars = {
            d: c
            for d, c in self.session.execute(
                select(DailyBar.trade_date, DailyBar.close).where(
                    DailyBar.ticker == position.ticker,
                    DailyBar.trade_date >= first,
                    DailyBar.trade_date <= end,
                )
            )
        }
        days = [d for d in business_days(first, end, self.holidays) if d in bars]
        if not days:
            return None
        dividends = load_dividends(self.session, position.ticker)
        quotes, stats = self._option_data(book, first, end)
        # Strike do cadastro numa consulta (revisão de performance, I-1: era uma por perna e pregão).
        self._strikes = dict(
            self.session.execute(
                select(OptionSeries.id, OptionSeries.strike).where(
                    OptionSeries.id.in_([o.series_id for o in book.options.values()])
                )
            ).all()
        )
        entry_prices = self._entry_prices(ledger)
        marks: list[DayMark] = []
        metas: list[dict[str, dict[str, Any]]] = []
        prev_legs: dict[str, LegMark] = {}
        prev_meta: dict[str, dict[str, Any]] = {}
        for day in days:
            spot = bars[day]
            q = holdings_until(ledger, day)
            legs, meta = self._mark_day(
                book, day, float(spot), q, dividends, quotes, stats, prev_legs, entry_prices
            )
            for code in legs:
                if code not in meta and code in prev_meta:
                    meta[code] = prev_meta[code] | {"days_to_expiry_bd": 0}
            marks.append(DayMark(day, spot, q.get(book.stock, 0), legs))
            metas.append(meta)
            prev_legs, prev_meta = legs, meta
        divs = {d: Decimal(repr(info.amount)) for d, info in dividends.items()}
        attribution = attribute_life(
            marks,
            ledger.transactions,
            stock_code=book.stock,
            dividends=divs,
            days_between=lambda a, b: count_business_days(a, b, self.holidays),
        )
        flags = [
            error_flag(a, max_ratio=self.journal.residual_max_ratio, min_brl=self.journal.residual_min_brl)
            for a in attribution
        ]
        return PositionMarks(marks, attribution, flags, ledger, book, metas)

    def _option_data(
        self, book: PositionBook, start: date, end: date
    ) -> tuple[dict[tuple[int, date], OptionDailyQuote], dict[tuple[int, date], OptionDailyStat]]:
        ids = [o.series_id for o in book.options.values()]
        quotes = {
            (q.series_id, q.trade_date): q
            for q in self.session.scalars(
                select(OptionDailyQuote).where(
                    OptionDailyQuote.series_id.in_(ids),
                    OptionDailyQuote.trade_date >= start,
                    OptionDailyQuote.trade_date <= end,
                )
            )
        }
        stats = {
            (s.series_id, s.trade_date): s
            for s in self.session.scalars(
                select(OptionDailyStat).where(
                    OptionDailyStat.series_id.in_(ids),
                    OptionDailyStat.trade_date >= start,
                    OptionDailyStat.trade_date <= end,
                )
            )
        }
        return quotes, stats

    @staticmethod
    def _entry_prices(ledger: Ledger) -> dict[str, float]:
        out: dict[str, float] = {}
        for tx in ledger.transactions:
            if tx.instrument not in out and tx.price > 0:
                out[tx.instrument] = float(tx.price)
        return out

    def _mark_day(
        self,
        book: PositionBook,
        day: date,
        spot: float,
        quantities: dict[str, int],
        dividends: dict[date, DividendInfo],
        quotes: dict[tuple[int, date], OptionDailyQuote],
        stats: dict[tuple[int, date], OptionDailyStat],
        prev_legs: dict[str, LegMark],
        entry_prices: dict[str, float],
    ) -> tuple[dict[str, LegMark], dict[str, dict[str, Any]]]:
        rate = self.rates.on(day)
        rate_c = continuous_rate(rate if rate is not None else 0.0)
        out: dict[str, LegMark] = {}
        to_price: list[LegQuote] = []
        pvs: dict[str, float] = {}
        for code, opt in book.options.items():
            prev = prev_legs.get(code)
            if day > opt.expiry and prev is not None:
                # Vencida: fica o intrínseco do pregão do vencimento, sem Greeks.
                out[code] = LegMark(code, quantities.get(code, 0), prev.price, prev.iv, "expired", 0, 0, 0, 0)
                continue
            divs_until = [(ex, info.amount) for ex, info in dividends.items() if day < ex <= opt.expiry]
            pv = self._pv(day, divs_until, rate_c)
            pvs[code] = pv
            stat = stats.get((opt.series_id, day))
            raw_strike = float(stat.strike) if stat is not None else self._series_strike(opt.series_id)
            protected = self.vol.implied.dividend_protected_strikes
            k_eff = raw_strike - sum(a for _, a in divs_until) if protected else raw_strike
            h = count_business_days(day, opt.expiry, self.holidays) if day < opt.expiry else 0
            q = quotes.get((opt.series_id, day))
            if h <= 0:
                to_price.append(LegQuote(code, opt.is_call, k_eff, 0, prev.iv if prev else None, "expired"))
                continue
            if q is not None and q.iv is not None:
                to_price.append(
                    LegQuote(code, opt.is_call, float(q.effective_strike), h, float(q.iv), "observed")
                )
                continue
            t = h / BUSINESS_DAYS_PER_YEAR
            observed = float(stat.last) if stat is not None and stat.last > 0 else None
            origin = "approximate"
            if observed is None and prev is None:
                observed = entry_prices.get(code)
            if observed is not None:
                res = implied_vol(observed, spot, k_eff, t, rate_c, opt.is_call, pv)
                if int(res.status[()]) == IvStatus.OK:
                    to_price.append(
                        LegQuote(
                            code, opt.is_call, k_eff, h, float(res.iv[()]), origin, price_override=observed
                        )
                    )
                    continue
            if prev is not None and prev.iv is not None:
                to_price.append(LegQuote(code, opt.is_call, k_eff, h, prev.iv, "stale"))
                continue
            raise ValueError(f"{code}: sem IV, fechamento nem marcação anterior em {day}.")
        # As pernas do mesmo vencimento compartilham o VP dos proventos.
        groups: dict[float, list[LegQuote]] = {}
        for lq in to_price:
            groups.setdefault(pvs[lq.code], []).append(lq)
        for pv_group, items in groups.items():
            out |= mark_legs(spot, rate_c, pv_group, items, quantities)
        meta = {
            lq.code: {
                "is_call": lq.is_call,
                "strike_eff": lq.strike_eff,
                "days_to_expiry_bd": int(lq.days_to_expiry_bd),
                "rate_c": rate_c,
                "pv_div": pvs[lq.code],
            }
            for lq in to_price
        }
        return out, meta

    def _pv(self, day: date, divs: list[tuple[date, float]], rate_c: float) -> float:
        return sum(
            amount * math.exp(-rate_c * count_business_days(day, ex, self.holidays) / BUSINESS_DAYS_PER_YEAR)
            for ex, amount in divs
        )

    def _series_strike(self, series_id: int) -> float:
        return float(self._strikes[series_id])


# --- Lançamentos (RF-DIA-02/03, RS-06) ---------------------------------------------------------


def lock_position(session: Session, position_id: int) -> None:
    """Trava a operação até o fim da transação: lançamentos concorrentes na mesma operação são
    validados um depois do outro (sem isso, duas saídas da mesma perna passariam juntas).

    Lock consultivo de transação: `SELECT … FOR UPDATE` exigiria UPDATE em `positions`, que o papel
    da aplicação não tem (tabela imutável). Espaço de chaves: (ADVISORY_NS_POSITION, id)."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :pid)"), {"ns": ADVISORY_NS_POSITION, "pid": position_id}
    )


def add_entry(session: Session, position: Position, body: EntryCreate, *, version_id: int) -> PositionEntry:
    """Valida pela reexecução do livro e grava o lançamento (imutável). `LedgerError` → 422."""
    lock_position(session, position.id)
    rows = load_entries(session, position.id)
    book = book_of(session, position.ticker, rows)
    existing = [ledger_entry(e) for e in rows]
    if body.kind == "void":
        target = next((e for e in rows if e.id == body.linked_entry_id), None)
        if target is None:
            raise LedgerError("Estorno de um lançamento que não é desta operação.")
        instrument, quantity, price = target.instrument, target.quantity, target.price
        series_id: int | None = target.series_id
    else:
        instrument = cast(str, body.instrument)
        quantity = cast(int, body.quantity)
        price = cast(Decimal, body.price_brl)
        opt = book.options.get(instrument)
        series_id = opt.series_id if opt is not None else None
    new = LedgerEntry(
        id=max((e.id for e in rows), default=0) + 1_000_000_000,  # provisório, só para a validação
        kind=EntryKind(body.kind),
        instrument=instrument,
        quantity=quantity,
        price=price,
        fees=body.fees_brl if body.kind != "void" else Decimal(0),
        brokerage=body.brokerage_brl if body.kind != "void" else Decimal(0),
        executed_at=body.executed_at,
        series_id=series_id,
        linked_entry_id=body.linked_entry_id,
        strike_after=body.strike_after_brl,
    )
    validate_new(existing, new, book, now=datetime.now(UTC))
    entry = PositionEntry(
        position_id=position.id,
        user_id=position.user_id,
        kind=body.kind,
        instrument=instrument,
        series_id=series_id,
        quantity=quantity,
        price=price,
        fees_brl=new.fees,
        brokerage_brl=new.brokerage,
        executed_at=body.executed_at,
        linked_entry_id=body.linked_entry_id,
        strike_after=body.strike_after_brl,
        void_reason=body.void_reason,
        note=body.note,
        config_version_id=version_id,
        engine_version=get_settings().engine_version,
    )
    session.add(entry)
    session.flush()
    enqueue_marks(session, user_id=position.user_id, position_ids=[position.id], reason="lançamento")
    return entry


# --- Leitura ------------------------------------------------------------------------------------


def _m(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def entry_out(e: PositionEntry, voided_by: dict[int, int]) -> EntryOut:
    return EntryOut(
        id=e.id,
        kind=cast(Any, e.kind),
        instrument=e.instrument,
        series_id=e.series_id,
        quantity=e.quantity,
        price_brl=_m(e.price),
        fees_brl=_m(e.fees_brl),
        brokerage_brl=_m(e.brokerage_brl),
        executed_at=e.executed_at,
        linked_entry_id=e.linked_entry_id,
        strike_after_brl=str(e.strike_after) if e.strike_after is not None else None,
        void_reason=e.void_reason,
        note=e.note,
        voided_by=voided_by.get(e.id),
    )


@dataclass(frozen=True, slots=True)
class Aggregate:
    pnl_total: Decimal | None
    last_mark: date | None
    ratio: float | None
    error_days: int


def aggregates(session: Session, position_ids: Sequence[int]) -> dict[int, Aggregate]:
    """P&L acumulado, última marcação, razão do CS-04 e dias com sinal de erro, numa consulta."""
    if not position_ids:
        return {}
    a = PnlAttribution
    explained = func.abs(a.delta_brl) + func.abs(a.gamma_brl) + func.abs(a.theta_brl) + func.abs(a.vega_brl)
    rows = session.execute(
        select(
            a.position_id,
            func.sum(a.market_brl + a.execution_brl),
            func.max(a.trade_date),
            func.sum(func.abs(a.residual_brl)),
            func.sum(explained),
            func.count().filter(a.error_flag),
        )
        .where(a.position_id.in_(position_ids))
        .group_by(a.position_id)
    ).all()
    out = {}
    for pid, total, last, res, expl, errors in rows:
        ratio = None if not expl else float(Decimal(res) / Decimal(expl))
        out[pid] = Aggregate(total, last, ratio, int(errors))
    return out


def status_of(session: Session, positions: Sequence[Position]) -> dict[int, tuple[Ledger, PositionBook]]:
    """Livro de cada posição (entradas e séries em duas consultas, sem o retrato JSONB)."""
    ids = [p.id for p in positions]
    if not ids:
        return {}
    rows = session.scalars(
        select(PositionEntry).where(PositionEntry.position_id.in_(ids)).order_by(PositionEntry.id)
    ).all()
    by_pos: dict[int, list[PositionEntry]] = {}
    for e in rows:
        by_pos.setdefault(e.position_id, []).append(e)
    series_ids = sorted({e.series_id for e in rows if e.series_id is not None})
    series = {s.id: s for s in session.scalars(select(OptionSeries).where(OptionSeries.id.in_(series_ids)))}
    out = {}
    for p in positions:
        entries = by_pos.get(p.id, [])
        options = {
            series[e.series_id].code: OptionInfo(
                series[e.series_id].code,
                e.series_id,
                series[e.series_id].option_type == "call",
                series[e.series_id].expiry,
                series[e.series_id].style == "european",
            )
            for e in entries
            if e.series_id is not None and e.series_id in series
        }
        book = PositionBook(p.ticker, options)
        out[p.id] = (replay_or_flag([ledger_entry(e) for e in entries], book), book)
    return out


def _summary(
    p: Position, ledger: Ledger, book: PositionBook, agg: Aggregate | None, today: date
) -> dict[str, Any]:
    return {
        "id": p.id,
        "created_at": p.created_at,
        "ticker": p.ticker,
        "structure": p.structure,
        "direction": p.direction,
        "expiry": p.expiry,
        "lots": p.lots,
        "edge_state": p.edge_state,
        "model": p.model,
        "config_version_id": p.config_version_id,
        "overridden": p.override_reason is not None,
        "status": "open" if ledger.is_open else "closed",
        "rolled_from_position_id": p.rolled_from_position_id,
        "pnl_total_brl": _m(agg.pnl_total) if agg is not None and agg.pnl_total is not None else None,
        "last_mark_date": agg.last_mark if agg is not None else None,
        "cs04_ratio": agg.ratio if agg is not None else None,
        "error_days": agg.error_days if agg is not None else 0,
        "pending_expiry": pending_expiry(ledger, book, today),
        "ledger_error": ledger.error,
    }


def summaries(session: Session, positions: Sequence[Position]) -> list[PositionSummary]:
    books = status_of(session, positions)
    aggs = aggregates(session, [p.id for p in positions])
    today = today_sao_paulo(get_settings())
    return [PositionSummary(**_summary(p, *books[p.id], aggs.get(p.id), today)) for p in positions]


def _attr_out(a: PnlAttribution) -> AttributionOut:
    return AttributionOut(
        trade_date=a.trade_date,
        delta_brl=_m(a.delta_brl),
        gamma_brl=_m(a.gamma_brl),
        theta_brl=_m(a.theta_brl),
        vega_brl=_m(a.vega_brl),
        residual_brl=_m(a.residual_brl),
        market_brl=_m(a.market_brl),
        execution_brl=_m(a.execution_brl),
        total_brl=_m(a.market_brl + a.execution_brl),
        stale=a.stale,
        error_flag=a.error_flag,
    )


def position_view(session: Session, p: Position) -> PositionOut:
    rows = load_entries(session, p.id)
    book = book_of(session, p.ticker, rows)
    ledger = replay_or_flag([ledger_entry(e) for e in rows], book)
    voided_by = {e.linked_entry_id: e.id for e in rows if e.kind == "void" and e.linked_entry_id}
    manual = session.scalars(
        select(ManualInput).where(ManualInput.position_id == p.id).order_by(ManualInput.id)
    ).all()
    marks = session.scalars(
        select(DailyMark).where(DailyMark.position_id == p.id).order_by(DailyMark.trade_date)
    ).all()
    attrs = session.scalars(
        select(PnlAttribution).where(PnlAttribution.position_id == p.id).order_by(PnlAttribution.trade_date)
    ).all()
    agg = aggregates(session, [p.id]).get(p.id)
    version = ensure_config_version(session, user_id=p.user_id)
    jp = journal_params_from_config(version)
    sim = simulation_params_from_config(version)
    size = sizing_params_from_config(version)
    today = today_sao_paulo(get_settings())

    def tot(field: str) -> Decimal:
        return sum((cast(Decimal, getattr(a, field)) for a in attrs), Decimal(0))

    totals = None
    if attrs:
        market, execution = tot("market_brl"), tot("execution_brl")
        totals = TotalsOut(
            delta_brl=_m(tot("delta_brl")),
            gamma_brl=_m(tot("gamma_brl")),
            theta_brl=_m(tot("theta_brl")),
            vega_brl=_m(tot("vega_brl")),
            residual_brl=_m(tot("residual_brl")),
            market_brl=_m(market),
            execution_brl=_m(execution),
            total_brl=_m(market + execution),
        )
    ratio = agg.ratio if agg is not None else None
    half = sim.delta_band * size.lot_size * p.lots
    last = marks[-1] if marks else None
    band = DeltaBandOut(
        as_of=last.trade_date if last else None,
        delta_shares=last.delta_shares if last else None,
        half_width_shares=half,
        calibrated=False,
        state=cast(Any, delta_band_state(last.delta_shares, half))
        if last and ledger.is_open
        else "unavailable",
    )
    return PositionOut(
        **_summary(p, ledger, book, agg, today),
        as_of=p.as_of,
        engine_version=p.engine_version,
        override_reason=p.override_reason,
        note=p.note,
        entries=[entry_out(e, voided_by) for e in rows],
        manual_inputs=[
            ManualInputOut(
                kind=cast(Any, m.kind),
                instrument=m.instrument,
                value_brl=_m(m.value),
                observed_at=m.observed_at,
            )
            for m in manual
        ],
        decision_snapshot=p.decision_snapshot,
        holdings=[
            HoldingOut(
                instrument=code,
                series_id=book.options[code].series_id if code in book.options else None,
                quantity=q,
            )
            for code, q in sorted(ledger.holdings.items())
        ],
        marks=[
            MarkOut(
                trade_date=m.trade_date,
                spot_brl=_m(m.spot),
                stock_qty=m.stock_qty,
                options_value_brl=_m(m.options_value),
                stock_value_brl=_m(m.stock_value),
                delta_shares=m.delta_shares,
                gamma=m.gamma,
                vega_per_point_brl=m.vega_per_point_brl,
                theta_per_bd_brl=m.theta_per_bd_brl,
                stale=m.stale,
                legs=[
                    MarkLegOut(
                        code=leg["code"],
                        quantity=leg["quantity"],
                        price_brl=_m(Decimal(leg["price_brl"])),
                        iv=leg["iv"],
                        origin=leg["origin"],
                        delta=leg["delta"],
                        gamma=leg["gamma"],
                        vega_per_point=leg["vega_per_point"],
                        theta_per_bd=leg["theta_per_bd"],
                    )
                    for leg in m.legs
                ],
            )
            for m in marks
        ],
        attribution=[_attr_out(a) for a in attrs],
        totals=totals,
        cs04=Cs04Out(
            ratio=ratio,
            target=jp.residual_max_ratio,
            ok=None if ratio is None else ratio < jp.residual_max_ratio,
            error_days=agg.error_days if agg is not None else 0,
        ),
        delta_band=band,
    )
