"""Salto de evento e IV de prazo constante ex-evento (RN-EVT-01..03, RF-VOL-03).

Calculados na leitura a partir de agregados já gravados (estrutura a termo ATM, OHLC diário e RV),
sem tocar negócios brutos (PRD-NF-06): dependem do calendário do usuário, que muda a qualquer
momento, e são baratos.

- Pela estrutura a termo (eq. 5.3 da referência): o primeiro vencimento depois do evento e o
  seguinte; se σ₁ ≤ σ₂ o mercado não precifica salto.
- Pelo histórico: retornos (log, ajustados por proventos) nas datas de resultado passadas
  cadastradas, menos a variância diária normal (close-to-close da maior janela).
- Combinado (RN-EVT-02): a estrutura a termo é a base; o intervalo vem do histórico
  (qui-quadrado, largo com poucos eventos) e é estendido para conter o valor da estrutura a termo.
  Sem histórico, não há intervalo, e isso aparece com o motivo.
"""

import bisect
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from vollab.analytics.market import DailySeries, load_daily_series, load_dividends, load_holidays
from vollab.analytics.params import VolParams
from vollab.db.models import AtmTermPoint, ConstantMaturityVol, Event, RealizedVol
from vollab.quant.implied import TermPoint, constant_maturity, event_vol, historical_jump
from vollab.quant.pricing import BUSINESS_DAYS_PER_YEAR

JUMP_KINDS = ("earnings",)


@dataclass(frozen=True, slots=True)
class TermPointRow:
    expiry: date
    days_bd: int
    iv: float


@dataclass(frozen=True, slots=True)
class JumpEstimate:
    event_id: int
    event_date: date
    as_of: date
    # Estrutura a termo
    ts_value: float | None
    ts_reason: str | None
    expiry1: date | None
    expiry2: date | None
    # Histórico
    hist_value: float | None
    hist_ci_low: float | None
    hist_ci_high: float | None
    hist_n: int
    # Combinado
    value: float | None
    ci_low: float | None
    ci_high: float | None
    origin: str  # estimated (estrutura a termo) | approximate (só histórico)
    reason: str | None

    @property
    def expected_move(self) -> float | None:
        """E|R| = sqrt(2/π)·σ_E (eq. 5.4)."""
        return None if self.value is None else math.sqrt(2.0 / math.pi) * self.value


def load_term_structure(session: Session, ticker: str) -> dict[date, list[TermPointRow]]:
    rows = session.execute(
        select(AtmTermPoint.as_of, AtmTermPoint.expiry, AtmTermPoint.days_to_expiry_bd, AtmTermPoint.atm_iv)
        .where(AtmTermPoint.ticker == ticker, AtmTermPoint.status == "ok")
        .order_by(AtmTermPoint.as_of, AtmTermPoint.expiry)
    )
    out: dict[date, list[TermPointRow]] = defaultdict(list)
    for as_of, expiry, du, iv in rows:
        if iv is not None:
            out[as_of].append(TermPointRow(expiry, du, float(iv)))
    return out


def jump_events(session: Session, *, user_id: uuid.UUID, ticker: str) -> list[Event]:
    return list(
        session.scalars(
            select(Event)
            .where(Event.user_id == user_id, Event.ticker == ticker, Event.kind.in_(JUMP_KINDS))
            .order_by(Event.event_date)
        )
    )


def _normal_variance_series(session: Session, ticker: str, params: VolParams) -> list[tuple[date, float]]:
    """Variância anualizada do close-to-close oficial na maior janela, por pregão (uma consulta só)."""
    estimator = "close_to_close" if params.close_to_close_mode == "zero_mean" else "close_to_close_demeaned"
    rows = session.execute(
        select(RealizedVol.as_of, RealizedVol.variance_annual)
        .where(
            RealizedVol.ticker == ticker,
            RealizedVol.estimator == estimator,
            RealizedVol.window_bd == max(params.windows_bd),
            RealizedVol.status == "ok",
        )
        .order_by(RealizedVol.as_of)
    )
    return [(d, float(v)) for d, v in rows if v is not None]


def _event_returns(series: DailySeries | None, events: list[Event], as_of: date) -> list[float]:
    if series is None:
        return []
    out = []
    for e in events:
        if e.event_date > as_of:
            continue
        i = series.index(e.event_date)
        if i is None:
            continue
        c, p = series.close[i], series.prev_close_adj[i]
        if math.isfinite(c) and math.isfinite(p) and p > 0:
            out.append(math.log(c / p))
    return out


def estimate_jump(
    event: Event,
    term: list[TermPointRow],
    as_of: date,
    *,
    past_returns: list[float],
    normal_daily_variance: float | None,
    ci_level: float,
) -> JumpEstimate:
    # Estrutura a termo: 1º vencimento depois do evento e o seguinte (eq. 5.3).
    ts_value: float | None = None
    ts_reason: str | None = None
    e1 = e2 = None
    after = [p for p in term if p.expiry > event.event_date and p.days_bd > 0]
    if event.event_date <= as_of:
        ts_reason = "evento já ocorreu"
    elif len(after) < 2:
        ts_reason = "sem dois vencimentos com IV ATM depois do evento"
    else:
        p1, p2 = after[0], after[1]
        e1, e2 = p1.expiry, p2.expiry
        ts_value = event_vol(
            p1.iv, p1.days_bd / BUSINESS_DAYS_PER_YEAR, p2.iv, p2.days_bd / BUSINESS_DAYS_PER_YEAR
        )
        if ts_value is None:
            ts_reason = "a estrutura a termo não precifica salto (IV do 1º vencimento ≤ a do 2º)"
    hist = historical_jump(past_returns, normal_daily_variance or 0.0, ci_level=ci_level)

    value = ts_value if ts_value is not None else hist.value
    origin = "estimated" if ts_value is not None else "approximate"
    ci_low, ci_high = hist.ci_low, hist.ci_high
    reason: str | None = None
    if value is None:
        reason = ts_reason or "sem estimativa pela estrutura a termo e sem histórico de resultados"
    elif hist.n == 0:
        ci_low = ci_high = None
        reason = "sem histórico de resultados cadastrados: intervalo indisponível"
    elif ci_low is not None and ci_high is not None:
        ci_low, ci_high = min(ci_low, value), max(ci_high, value)
    return JumpEstimate(
        event_id=event.id,
        event_date=event.event_date,
        as_of=as_of,
        ts_value=ts_value,
        ts_reason=ts_reason,
        expiry1=e1,
        expiry2=e2,
        hist_value=hist.value,
        hist_ci_low=hist.ci_low,
        hist_ci_high=hist.ci_high,
        hist_n=hist.n,
        value=value,
        ci_low=ci_low,
        ci_high=ci_high,
        origin=origin,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class ConstantMaturityPoint:
    as_of: date
    iv: float | None
    iv_reason: str | None
    iv_ex_event: float | None
    ex_event_reason: str | None
    events_removed: list[int]
    fallback_expiry: date | None
    fallback_bd: int | None
    fallback_iv: float | None
    lower_expiry: date | None
    upper_expiry: date | None


class EventContext:
    """Dados de um ativo para calcular saltos e IV ex-evento em várias datas."""

    def __init__(self, session: Session, *, user_id: uuid.UUID, ticker: str, params: VolParams) -> None:
        self.session = session
        self.ticker = ticker
        self.params = params
        self.term = load_term_structure(session, ticker)
        self.events = jump_events(session, user_id=user_id, ticker=ticker)
        holidays = load_holidays(session)
        self.series = load_daily_series(session, ticker, holidays, load_dividends(session, ticker))
        normal = _normal_variance_series(session, ticker, params)
        self._normal_days = [d for d, _ in normal]
        self._normal_values = [v for _, v in normal]

    def _normal_daily_variance(self, as_of: date) -> float | None:
        """Última variância normal até `as_of`, diária (÷ 252)."""
        i = bisect.bisect_right(self._normal_days, as_of) - 1
        return self._normal_values[i] / BUSINESS_DAYS_PER_YEAR if i >= 0 else None

    def jumps(self, as_of: date) -> list[JumpEstimate]:
        """Saltos dos eventos futuros (depois de `as_of`), com o histórico até `as_of`."""
        past = _event_returns(self.series, self.events, as_of)
        normal = self._normal_daily_variance(as_of)
        term = self.term.get(as_of, [])
        return [
            estimate_jump(
                e, term, as_of, past_returns=past, normal_daily_variance=normal, ci_level=self.params.ci_level
            )
            for e in self.events
            if e.event_date > as_of
        ]

    def constant_maturity_history(self, days: int = 252) -> list[ConstantMaturityPoint]:
        """Os últimos `days` pregões (histórico limitado: o custo cresce com ele)."""
        target = self.params.constant_maturity_bd
        rows = list(
            reversed(
                self.session.scalars(
                    select(ConstantMaturityVol)
                    .where(ConstantMaturityVol.ticker == self.ticker, ConstantMaturityVol.target_bd == target)
                    .order_by(ConstantMaturityVol.as_of.desc())
                    .limit(days)
                ).all()
            )
        )
        out = []
        for row in rows:
            ex, ex_reason, removed = self._ex_event(row.as_of, row.iv)
            out.append(
                ConstantMaturityPoint(
                    as_of=row.as_of,
                    iv=row.iv,
                    iv_reason=row.reason,
                    iv_ex_event=ex,
                    ex_event_reason=ex_reason,
                    events_removed=removed,
                    fallback_expiry=row.fallback_expiry,
                    fallback_bd=row.fallback_bd,
                    fallback_iv=row.fallback_iv,
                    lower_expiry=row.lower_expiry,
                    upper_expiry=row.upper_expiry,
                )
            )
        return out

    def _ex_event(self, as_of: date, raw_iv: float | None) -> tuple[float | None, str | None, list[int]]:
        """RN-EVT-03: remove a variância dos saltos dos eventos até cada vencimento e interpola de novo."""
        term = self.term.get(as_of, [])
        if not term:
            return None, "sem estrutura a termo no pregão", []
        upcoming = [e for e in self.events if e.event_date > as_of]
        horizon = max(p.expiry for p in term)
        relevant = [e for e in upcoming if e.event_date < horizon]
        if not relevant:
            return raw_iv, (None if raw_iv is not None else "IV de prazo constante indisponível"), []
        jumps = {j.event_id: j for j in self.jumps(as_of)}
        if any(jumps[e.id].value is None for e in relevant):
            return None, "salto de evento sem estimativa", []
        points = [
            TermPoint(
                p.days_bd / BUSINESS_DAYS_PER_YEAR,
                p.iv,
                sum((jumps[e.id].value or 0.0) ** 2 for e in relevant if e.event_date < p.expiry),
            )
            for p in term
        ]
        cm = constant_maturity(points, self.params.constant_maturity_bd / BUSINESS_DAYS_PER_YEAR)
        return cm.iv, cm.reason, [e.id for e in relevant]

    # Leitura pontual (ranking, PRD 1.8 §5.6.1) ---------------------------------------------

    def ex_event_iv(self, as_of: date, raw_iv: float | None) -> tuple[float | None, str | None, list[int]]:
        """IV de prazo constante ex-evento no pregão (RN-EVT-03)."""
        return self._ex_event(as_of, raw_iv)

    def ex_event_atm(
        self, as_of: date, expiry: date, days_bd: int, iv: float
    ) -> tuple[float | None, str | None, list[int]]:
        """IV ATM de um vencimento sem os saltos dos eventos até ele (fallback do RN-VOL-05)."""
        relevant = [e for e in self.events if as_of < e.event_date < expiry]
        if not relevant:
            return iv, None, []
        jumps = {j.event_id: j for j in self.jumps(as_of)}
        if any(jumps[e.id].value is None for e in relevant):
            return None, "salto de evento sem estimativa", []
        t = days_bd / BUSINESS_DAYS_PER_YEAR
        w = iv * iv * t - sum((jumps[e.id].value or 0.0) ** 2 for e in relevant)
        if w <= 0:
            return None, "variância ex-evento não positiva", []
        return math.sqrt(w / t), None, [e.id for e in relevant]
