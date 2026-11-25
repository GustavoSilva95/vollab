"""Gestão da operação: avaliação das regras e alertas (PRD 1.11 §5.10; BRD 1.8 RN-GES-01..07, RS-07).

Job `alerts_evaluate` (worker), enfileirado ao fim de cada `marks_recompute` e depois de cada nova
versão de configuração. Avalia cada posição aberta na última marcação D-1 (pregão *t*) e a carteira,
grava o estado das regras em `position_management` (lido por `GET /positions/{id}`) e reconcilia a
tabela `alerts` (cria, atualiza, resolve). Não recalcula marcações: lê o que o diário já gravou.
"""

import functools
import math
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, defer

from vollab.analytics.journal import aggregates, load_entries, status_of
from vollab.analytics.params import (
    ManagementParams,
    SimulationParams,
    SizingParams,
    management_params_from_config,
    simulation_params_from_config,
    sizing_params_from_config,
)
from vollab.analytics.portfolio import PortfolioComputer
from vollab.analytics.simulation import SimulationComputer, SimulationInputError, money
from vollab.api.schemas.simulation import ChainResponse, LegInput, SimulationRequest
from vollab.collection.params import ensure_config_version
from vollab.db.models import (
    FIXED_USER_ID,
    Alert,
    CorporateAction,
    DailyMark,
    Job,
    JobStatus,
    Position,
    PositionEntry,
    PositionManagement,
    SeriesAdjustment,
)
from vollab.jobs import queue
from vollab.jobs.handlers import register
from vollab.quant.calendar import business_days, count_business_days
from vollab.quant.costs import Band, hedge_cost, moneyness_band, spread_estimate
from vollab.quant.edge import Direction, EdgeState, premium
from vollab.quant.journal import Ledger, PositionBook
from vollab.quant.management import (
    LIMIT_RULES,
    Key,
    OpenAlert,
    PositionEdge,
    RuleResult,
    RuleState,
    exit_dte,
    exit_edge,
    exit_profit,
    exit_stop,
    hedge_band,
    hedge_time,
    in_dividend_window,
    position_edge,
    reconcile,
    roll_expiry,
)
from vollab.quant.pricing import BUSINESS_DAYS_PER_YEAR
from vollab.quant.risk import LimitState
from vollab.quant.simulation import DYNAMIC_HEDGE, Structure
from vollab.settings import get_settings

log = structlog.get_logger("vollab.management")
JOB_KIND = "alerts_evaluate"


# --- Fila --------------------------------------------------------------------------------------


def enqueue_alerts(session: Session, *, user_id: uuid.UUID, reason: str) -> None:
    """Um pedido na fila absorve os seguintes (a avaliação é sempre da carteira inteira)."""
    queued = session.scalar(
        select(Job.id)
        .where(Job.kind == JOB_KIND, Job.user_id == user_id, Job.status == JobStatus.QUEUED)
        .limit(1)
    )
    if queued is not None:
        return
    queue.enqueue(
        session,
        user_id=user_id,
        kind=JOB_KIND,
        payload={"user_id": str(user_id), "reason": reason},
        max_attempts=3,
    )


@register(JOB_KIND)
def run_alerts_job(session: Session, payload: dict[str, Any]) -> None:
    user_id = uuid.UUID(str(payload.get("user_id") or FIXED_USER_ID))
    AlertsEvaluator(session, user_id=user_id).run()


# --- Avaliação ---------------------------------------------------------------------------------


@dataclass(slots=True)
class Evaluation:
    """Resultado de uma posição: regras, edge da posição e rolagem avaliada."""

    as_of: date | None
    rules: list[RuleResult]
    edge: dict[str, Any] | None
    roll: dict[str, Any] | None


def _dec(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None
    return out if math.isfinite(out) else None


class AlertsEvaluator:
    def __init__(self, session: Session, *, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id
        version = ensure_config_version(session, user_id=user_id)
        session.commit()
        self.version_id = version.id
        self.mg: ManagementParams = management_params_from_config(version)
        self.sim: SimulationParams = simulation_params_from_config(version)
        self.size: SizingParams = sizing_params_from_config(version)
        # Um só RankingComputer, compartilhado com o simulador da rolagem, com as leituras por
        # (ativo, pregão) memorizadas na rodada (revisão de performance da Etapa 8, I-1 a I-3).
        self.sc = SimulationComputer(session, user_id=user_id)
        self.rk = self.sc.rk
        for name in ("spread_days", "forecast_value", "normal_spread_value"):
            setattr(self.rk, name, functools.lru_cache(maxsize=None)(getattr(self.rk, name)))
        self.holidays = self.rk.holidays
        self.engine_version = get_settings().engine_version
        self._chains: dict[tuple[str, date | None], ChainResponse] = {}

    def chain(self, ticker: str, expiry: date | None) -> ChainResponse:
        key = (ticker, expiry)
        if key not in self._chains:
            self._chains[key] = self.sc.chain(ticker, expiry)
        return self._chains[key]

    # Rodada completa ------------------------------------------------------------------------------

    def run(self) -> None:
        s = self.session
        positions = s.scalars(
            select(Position)
            .options(defer(Position.decision_snapshot))
            .where(Position.user_id == self.user_id)
            .order_by(Position.id)
        ).all()
        books = status_of(s, positions)
        open_ = [p for p in positions if books[p.id][0].is_open and not books[p.id][0].error]
        closed_ids = {p.id for p in positions if not books[p.id][0].is_open and not books[p.id][0].error}
        marks = self._last_marks([p.id for p in open_])
        aggs = aggregates(s, [p.id for p in open_])
        snapshots = self._snapshot_numbers([p.id for p in open_])

        firing: dict[Key, tuple[RuleResult, date]] = {}
        evaluated_positions: set[int] = set(closed_ids)
        reasons_closed = {pid: "operação encerrada" for pid in closed_ids}
        for p in open_:
            ledger, book = books[p.id]
            mark = marks.get(p.id)
            agg = aggs.get(p.id)
            pnl = float(agg.pnl_total) if agg is not None and agg.pnl_total is not None else None
            try:
                ev = self.evaluate_position(p, ledger, book, mark, pnl, snapshots.get(p.id, (None, None)))
            except (ValueError, LookupError) as exc:  # um ativo sem dado não derruba a carteira
                log.warning("alerts.position_skipped", position_id=p.id, error=type(exc).__name__)
                continue
            self._store_management(p.id, ev)
            if ev.as_of is None:
                continue  # sem marcação: nada é resolvido por falta de dado
            evaluated_positions.add(p.id)
            for r in ev.rules:
                if r.triggered:
                    firing[(r.rule, p.id, r.scope_key)] = (r, ev.as_of)
        s.execute(delete(PositionManagement).where(PositionManagement.position_id.in_(closed_ids)))

        limits_ok = False
        limits_as_of = max((m.trade_date for m in marks.values()), default=None) or self.rk.expected_as_of
        try:
            for r in self.limit_rules():
                if r.triggered:
                    firing[(r.rule, None, r.scope_key)] = (r, limits_as_of)
            limits_ok = True
        except (ValueError, LookupError) as exc:
            log.warning("alerts.limits_skipped", error=type(exc).__name__)

        def evaluated(key: Key) -> bool:
            return limits_ok if key[1] is None else key[1] in evaluated_positions

        self.apply(firing, evaluated, reasons_closed)
        s.commit()

    def _last_marks(self, ids: Sequence[int]) -> dict[int, DailyMark]:
        if not ids:
            return {}
        rows = self.session.scalars(
            select(DailyMark)
            .where(DailyMark.position_id.in_(ids))
            .order_by(DailyMark.position_id, DailyMark.trade_date.desc())
            .ext(distinct_on(DailyMark.position_id))
        ).all()
        return {m.position_id: m for m in rows}

    def _snapshot_numbers(self, ids: Sequence[int]) -> dict[int, tuple[float | None, float | None]]:
        """P&L esperado e perda máxima **por lote** do retrato (só quando meta ou stop estão ligados)."""
        if not ids or (self.mg.profit_target_fraction is None and self.mg.stop_loss_fraction is None):
            return {}
        snap = Position.decision_snapshot
        rows = self.session.execute(
            select(
                Position.id,
                snap["simulation"]["expected_pnl_brl"].astext,
                snap["sizing"]["max_loss_brl"].astext,
            ).where(Position.id.in_(ids))
        ).all()
        return {pid: (_dec(exp), _dec(loss)) for pid, exp, loss in rows}

    # Uma posição ---------------------------------------------------------------------------------

    def evaluate_position(
        self,
        p: Position,
        ledger: Ledger,
        book: PositionBook,
        mark: DailyMark | None,
        pnl: float | None,
        snapshot: tuple[float | None, float | None],
    ) -> Evaluation:
        half = self.sim.delta_band * self.size.lot_size * p.lots
        if mark is None:
            rules = [
                hedge_band(None, half),
                hedge_time(None, self.mg.hedge_interval_bd, None),
                exit_edge(None, "sem marcação D-1"),
                exit_dte(None, self.mg.exit_dte_bd),
                exit_profit(None, None, self.mg.profit_target_fraction),
                exit_stop(None, None, self.mg.stop_loss_fraction),
            ]
            return Evaluation(None, rules, None, None)
        t = mark.trade_date
        delta = float(mark.delta_shares)
        entries = load_entries(self.session, p.id)
        voided = {e.linked_entry_id for e in entries if e.kind == "void"}
        active = [e for e in entries if e.kind != "void" and e.id not in voided]
        hedge_days = [e.executed_at.astimezone(UTC).date() for e in active if e.kind == "hedge"]
        start_day = (
            max(hedge_days) if hedge_days else min(e.executed_at.astimezone(UTC).date() for e in active)
        )
        bd_since = count_business_days(start_day, t, self.holidays)

        legs = [leg for leg in mark.legs if leg["quantity"] != 0 and "days_to_expiry_bd" in leg]
        dte = min((int(leg["days_to_expiry_bd"]) for leg in legs), default=None)
        edge, edge_reason, edge_json, close_brl = self.position_edge(p, mark, legs)
        exp_lot, loss_lot = snapshot
        rules = [
            hedge_band(delta, half),
            hedge_time(bd_since, self.mg.hedge_interval_bd, delta),
            exit_edge(edge, edge_reason),
            exit_dte(dte, self.mg.exit_dte_bd),
            exit_profit(pnl, None if exp_lot is None else exp_lot * p.lots, self.mg.profit_target_fraction),
            exit_stop(pnl, None if loss_lot is None else loss_lot * p.lots, self.mg.stop_loss_fraction),
            *self.dividend_rules(p, t),
            *self.strike_adjustment_rules(p, book, ledger, active),
        ]
        roll: dict[str, Any] | None = None
        if any(r.triggered and r.rule in ("exit_edge", "exit_dte") for r in rules):
            roll = self.roll(p, close_brl)
            state = RuleState.TRIGGERED if roll.get("suggested") else RuleState.OK
            if roll.get("status") == "unavailable":
                state = RuleState.UNAVAILABLE
            rules.append(RuleResult("roll_suggested", state, details=roll, reason=roll.get("reason")))
        return Evaluation(t, rules, edge_json, roll)

    def position_edge(
        self, p: Position, mark: DailyMark, legs: list[dict[str, Any]]
    ) -> tuple[PositionEdge | None, str | None, dict[str, Any] | None, float | None]:
        """Edge relativo líquido da posição aberta (RN-GES-02, G1): "eu manteria esta posição agora?"."""
        t = mark.trade_date
        spot = float(mark.spot)
        c = self.rk.p.costs
        live = [leg for leg in legs if int(leg["days_to_expiry_bd"]) >= 1 and leg.get("iv") is not None]
        # Custo de fechar: pernas abertas + ação em carteira (meio spread conservador + taxas).
        und = spread_estimate(self.rk.spread_days(p.ticker, t, Band.UNDERLYING))
        und_spread = und.conservative if und else c.tick_brl / spot
        stock_brl = abs(mark.stock_qty) * spot * (und_spread / 2.0 + c.underlying_fee_rate)
        if not live:
            return None, "sem pernas de opção abertas antes do vencimento", None, stock_brl
        h = int(live[0]["days_to_expiry_bd"])
        weights = [abs(leg["quantity"] * leg["vega_per_point"]) for leg in live]
        vega_unit = abs(sum(leg["quantity"] * leg["vega_per_point"] for leg in live)) * 100.0
        if sum(weights) <= 0 or vega_unit <= 0:
            return None, "vega da posição nula", None, None
        iv_raw = sum(w * float(leg["iv"]) for w, leg in zip(weights, live, strict=True)) / sum(weights)
        ctx = self.sc.event_context(p.ticker)
        iv_ex, ex_reason, _ = ctx.ex_event_atm(t, p.expiry, h, iv_raw)
        approximate = iv_ex is None
        iv = iv_raw if iv_ex is None else iv_ex
        forecast = self.rk.forecast_value(p.ticker, t, h, self.rk.p.forecast.selected_model, approximate)
        missing_spread = []
        close_brl = stock_brl
        for leg in live:
            rate_c, pv = float(leg["rate_c"]), float(leg["pv_div"])
            fwd = (spot - pv) * math.exp(rate_c * h / BUSINESS_DAYS_PER_YEAR)
            band = moneyness_band(float(leg["strike_eff"]) / fwd, c.moneyness_bands)
            est = spread_estimate(self.rk.spread_days(p.ticker, t, band))
            if est is None:
                missing_spread.append(leg["code"])
                continue
            price = float(leg["price_brl"])
            q = abs(int(leg["quantity"]))
            close_brl += q * price * (est.conservative / 2.0 + c.option_fee_rate + c.brokerage_rate)
            close_brl += c.brokerage_per_order_brl
        if missing_spread:
            return None, f"sem estimativa de spread para {', '.join(missing_spread)}", None, None
        if forecast.status != "ok" or forecast.value is None:
            return None, forecast.reason or "sem previsão de RV", None, close_brl
        sigma = float(forecast.value)
        lo = float(forecast.ci_low) if forecast.ci_low is not None else sigma
        hi = float(forecast.ci_high) if forecast.ci_high is not None else sigma
        ns, _ = self.rk.normal_spread_value(p.ticker, t)
        prem = premium(iv, sigma, lo, hi, float(cast(float, ns.value)))
        direction = Direction(p.direction)
        if DYNAMIC_HEDGE[Structure(p.structure)]:
            hc = hedge_cost(
                sigma,
                underlying_rel_spread=und_spread,
                fee_rate=c.underlying_fee_rate,
                interval_bd=c.hedge_interval_bd,
            )
            cost_hold = hc.sell if direction is Direction.SELL else hc.buy
        else:
            cost_hold = 0.0
        edge = position_edge(
            prem, sigma=sigma, direction=direction, cost_hold=cost_hold, cost_close=close_brl / vega_unit
        )
        reason = None
        if approximate:
            reason = "IV com evento: não foi possível separar o salto" + (
                f" ({ex_reason})" if ex_reason else ""
            )
        edge_json = {
            "as_of": t.isoformat(),
            "horizon_bd": h,
            "iv": iv,
            "iv_with_events": iv_raw,
            "sigma": sigma,
            "sigma_low": lo,
            "sigma_high": hi,
            "normal_spread": ns.value,
            "normal_spread_calibrated": ns.calibrated,
            "premium": prem.value,
            "premium_low": prem.ci_low,
            "premium_high": prem.ci_high,
            "cost_hold_vol_pts": cost_hold,
            "cost_close_vol_pts": edge.cost_close,
            "cost_close_brl": close_brl,
            "net_relative_edge": edge.value,
            "net_relative_low": edge.ci_low,
            "net_relative_high": edge.ci_high,
            "origin": "approximate" if approximate or forecast.origin == "approximate" else "estimated",
            "model": self.rk.p.forecast.selected_model,
            "reason": reason,
        }
        return edge, reason, edge_json, close_brl

    def dividend_rules(self, p: Position, t: date) -> list[RuleResult]:
        """Data ex em (t, t + N du] para o ativo da posição (RN-GES-06)."""
        n = self.mg.dividend_lead_bd
        if n <= 0:
            return []
        window_end = nth_business_day_after(t, n, self.holidays)
        rows = self.session.scalars(
            select(CorporateAction).where(
                CorporateAction.ticker == p.ticker,
                CorporateAction.ex_date > t,
                CorporateAction.ex_date <= window_end,
            )
        ).all()
        by_day: dict[date, list[CorporateAction]] = {}
        for ca in rows:
            if in_dividend_window(ca.ex_date, t, window_end):
                by_day.setdefault(ca.ex_date, []).append(ca)
        out = []
        for ex, items in sorted(by_day.items()):
            out.append(
                RuleResult(
                    "dividend_upcoming",
                    RuleState.TRIGGERED,
                    scope_key=ex.isoformat(),
                    details={
                        "ticker": p.ticker,
                        "ex_date": ex.isoformat(),
                        "days_to_ex_bd": count_business_days(t, ex, self.holidays),
                        "lead_bd": n,
                        "items": [
                            {
                                "kind": ca.kind,
                                "amount_brl": str(ca.amount),
                                "source": ca.source,
                                "confirmed": ca.confirmed,
                                "origin": "manual" if ca.source == "manual" else "estimated",
                            }
                            for ca in sorted(items, key=lambda x: x.source)
                        ],
                    },
                )
            )
        return out

    def strike_adjustment_rules(
        self, p: Position, book: PositionBook, ledger: Ledger, active: Sequence[PositionEntry]
    ) -> list[RuleResult]:
        """Ajuste de strike da B3 numa perna aberta sem o lançamento correspondente (RS-07)."""
        held = {code: opt for code, opt in book.options.items() if ledger.holdings.get(code, 0) != 0}
        if not held:
            return []
        by_id = {opt.series_id: code for code, opt in held.items()}
        adjs = self.session.scalars(
            select(SeriesAdjustment).where(
                SeriesAdjustment.series_id.in_(list(by_id)), SeriesAdjustment.effective_date > p.as_of
            )
        ).all()
        out = []
        for a in sorted(adjs, key=lambda x: (x.effective_date, x.series_id)):
            code = by_id[a.series_id]
            done = any(
                e.kind == "strike_adjustment"
                and e.instrument == code
                and e.executed_at.astimezone(UTC).date() >= a.previous_date
                for e in active
            )
            if done:
                continue
            out.append(
                RuleResult(
                    "strike_adjustment_pending",
                    RuleState.TRIGGERED,
                    scope_key=f"{code}:{a.effective_date.isoformat()}",
                    details={
                        "code": code,
                        "effective_date": a.effective_date.isoformat(),
                        "old_strike_brl": str(a.old_strike),
                        "new_strike_brl": str(a.new_strike),
                    },
                )
            )
        return out

    def roll(self, p: Position, close_brl: float | None) -> dict[str, Any]:
        """Destino: mesma estrutura no 1º vencimento (depois do atual) com ≥ N du e IV de referência;
        sugerida só com edge líquido na direção da posição, com o custo de fechar a atual."""
        base: dict[str, Any] = {
            "status": "unavailable",
            "suggested": False,
            "min_dte_bd": self.mg.roll_min_dte_bd,
        }
        if close_brl is None:
            return base | {"reason": "custo de fechar a posição atual indisponível"}
        try:
            chain = self.chain(p.ticker, None)
            if chain.as_of is None:
                return base | {"reason": "sem pregão para a cadeia de opções"}
            as_of = chain.as_of
            dest = roll_expiry(
                [e for e in chain.expiries_with_iv if e > p.expiry],
                lambda e: count_business_days(as_of, e, self.holidays),
                self.mg.roll_min_dte_bd,
            )
            if dest is None:
                return base | {
                    "reason": f"sem vencimento depois do atual com ≥ {self.mg.roll_min_dte_bd} du "
                    "e IV de referência"
                }
            dchain = self.chain(p.ticker, dest)
            ids = dchain.suggestions.get(p.structure)
            if not ids:
                return base | {"expiry": dest.isoformat(), "reason": "sem strikes sugeridos para a estrutura"}
            req = SimulationRequest(
                ticker=p.ticker,
                structure=cast(Any, p.structure),
                legs=[LegInput(series_id=i) for i in ids],
                lots=p.lots,
            )
            extra = close_brl / (self.size.lot_size * p.lots)
            se = self.sc.structure_edge(req, extra_cost_brl_unit=extra)
        except SimulationInputError as exc:
            return base | {"reason": str(exc)[:300]}
        except (LookupError, ValueError) as exc:  # mensagem interna fica só no log (segurança, M-4)
            log.warning("alerts.roll_unavailable", position_id=p.id, error=type(exc).__name__)
            return base | {"reason": "dados insuficientes para avaliar o destino da rolagem"}
        suggested = se.state == EdgeState.EDGE.value and se.signal_direction is Direction(p.direction)
        return {
            "status": "ok",
            "suggested": suggested,
            "min_dte_bd": self.mg.roll_min_dte_bd,
            "as_of": se.as_of.isoformat(),
            "expiry": se.expiry.isoformat(),
            "horizon_bd": se.horizon_bd,
            "structure": p.structure,
            "legs": [{"series_id": sid, "code": code} for sid, code in se.legs],
            "lots": p.lots,
            "state": se.state,
            "signal_direction": se.signal_direction.value if se.signal_direction else None,
            "iv": se.iv,
            "sigma": se.sigma,
            "premium": se.premium,
            "premium_low": se.p_low,
            "premium_high": se.p_high,
            "cost_sell_vol_pts": se.cost_sell,
            "cost_buy_vol_pts": se.cost_buy,
            "close_cost_brl": close_brl,
            "close_cost_vol_pts": se.extra_cost_vol_pts,
            "net_relative_edge": se.net_relative,
            "reason": se.reason
            if suggested
            else (se.reason or "rolagem avaliada: sem edge líquido na direção"),
        }

    # Carteira ------------------------------------------------------------------------------------

    def limit_rules(self) -> list[RuleResult]:
        out = []
        res = PortfolioComputer(self.session, user_id=self.user_id).limits()
        for x in res.limits:
            if x.state != LimitState.BREACHED.value:
                continue
            rule = LIMIT_RULES[x.name]
            out.append(
                RuleResult(
                    rule,
                    RuleState.TRIGGERED,
                    scope_key=x.scope or "",
                    details={
                        "limit": x.name,
                        "scope": x.scope,
                        "value": x.value,
                        "limit_value": x.limit,
                        "usage": x.usage,
                        "capital_brl": res.capital_brl,
                        "calibrated": False,
                    },
                )
            )
        return out

    # Gravação ------------------------------------------------------------------------------------

    def _store_management(self, position_id: int, ev: Evaluation) -> None:
        s = self.session
        row = s.get(PositionManagement, position_id)
        rules = [
            {
                "rule": r.rule,
                "kind": r.kind,
                "state": r.state.value,
                "scope_key": r.scope_key,
                "reason": r.reason,
                "details": _money_fields(dict(r.details)),
            }
            for r in ev.rules
        ]
        if row is None:
            row = PositionManagement(position_id=position_id)
            s.add(row)
        row.as_of = ev.as_of
        row.rules = rules
        row.edge = _money_fields(ev.edge)
        row.roll = _money_fields(ev.roll)
        row.config_version_id = self.version_id
        row.engine_version = self.engine_version
        row.evaluated_at = datetime.now(UTC)

    def apply(
        self,
        firing: dict[Key, tuple[RuleResult, date]],
        evaluated: Callable[[Key], bool],
        reasons_closed: dict[int, str],
    ) -> None:
        s = self.session
        # Lock nas linhas: um PATCH concorrente espera o commit do job e decide sobre o estado novo
        # (sem ele, resolver no meio da rodada fazia o trigger derrubar a rodada; segurança, M-1).
        open_rows = s.scalars(
            select(Alert)
            .where(Alert.user_id == self.user_id, Alert.state != "resolved")
            .order_by(Alert.id)
            .with_for_update()
        ).all()
        held_rows = s.scalars(
            select(Alert)
            .where(Alert.user_id == self.user_id, Alert.state == "resolved", Alert.persisting.is_(True))
            .order_by(Alert.id)
            .with_for_update()
        ).all()
        plan = reconcile(
            [OpenAlert(a.id, _key(a)) for a in open_rows],
            firing.keys(),
            [_key(a) for a in held_rows],
            evaluated,
        )
        now = datetime.now(UTC)
        by_id = {a.id: a for a in open_rows}
        for k in plan.create:
            r, as_of = firing[k]
            s.add(
                Alert(
                    user_id=self.user_id,
                    kind=r.kind,
                    rule=r.rule,
                    position_id=k[1],
                    scope_key=k[2],
                    state="active",
                    triggered_as_of=as_of,
                    last_as_of=as_of,
                    details=_details(r),
                    config_version_id=self.version_id,
                    evaluated_config_version_id=self.version_id,
                    engine_version=self.engine_version,
                )
            )
        for aid, k in plan.update:
            r, as_of = firing[k]
            a = by_id[aid]
            a.last_as_of = as_of
            a.details = _details(r)
            a.evaluated_config_version_id = self.version_id
        for aid in plan.resolve:
            a = by_id[aid]
            a.state = "resolved"
            a.resolved_at = now
            a.resolved_by = "auto"
            reason = reasons_closed.get(a.position_id or -1, "a condição deixou de valer")
            a.resolution_note = reason
            a.evaluated_config_version_id = self.version_id
        released = set(plan.release)
        for a in held_rows:
            if _key(a) in released:
                a.persisting = False


def _key(a: Alert) -> Key:
    return (a.rule, a.position_id, a.scope_key)


def nth_business_day_after(day: date, n: int, holidays: frozenset[date] | set[date]) -> date:
    """O n-ésimo pregão depois de `day` (n ≥ 1)."""
    days = business_days(day + timedelta(days=1), day + timedelta(days=7 * n + 30), holidays)
    for i, d in enumerate(days, start=1):
        if i == n:
            return d
    raise ValueError("nth_business_day_after: calendário sem pregões suficientes.")


def _money_fields(d: Any) -> Any:
    """Dinheiro em texto decimal (PRD §5.1): chaves `_brl` com float viram "123.45"."""
    if isinstance(d, dict):
        return {
            k: money(v) if k.endswith("_brl") and isinstance(v, float) else _money_fields(v)
            for k, v in d.items()
        }
    if isinstance(d, list):
        return [_money_fields(v) for v in d]
    return d


def _details(r: RuleResult) -> dict[str, Any]:
    return cast(dict[str, Any], _money_fields(dict(r.details) | ({"reason": r.reason} if r.reason else {})))


# --- Ações do usuário e leitura -------------------------------------------------------------------


class AlertTransitionError(ValueError):
    """Transição inválida (422) ou alerta já resolvido (409)."""

    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


def transition(alert: Alert, state: str, note: str | None) -> None:
    """`active` → `seen`; `active`/`seen` → `resolved` (pelo usuário). `resolved` é terminal."""
    if alert.state == "resolved":
        raise AlertTransitionError("Alerta já resolvido.", conflict=True)
    if state == "seen":
        if alert.state != "active":
            raise AlertTransitionError("Só um alerta ativo pode ser marcado como visto.")
        alert.state = "seen"
        return
    if state == "resolved":
        alert.state = "resolved"
        alert.resolved_at = datetime.now(UTC)
        alert.resolved_by = "user"
        alert.resolution_note = note
        # A condição ainda vale (o alerta não estava resolvido): segura a reabertura até ela sumir.
        alert.persisting = True
        return
    raise AlertTransitionError(f"Estado inválido: {state}.")
