"""Regras de gestão da operação (PRD 1.11 §5.10; BRD 1.8 RN-GES-01..07, RS-07). Sem I/O.

Cada regra devolve um `RuleResult` com o estado (`ok`, `triggered`, `disabled`, `unavailable`), o
escopo (para a chave do alerta) e os números que a tela mostra. Comparações:
- banda de delta: estrita (igual à borda não dispara), como o indicador da Etapa 7;
- "o edge acabou": edge relativo líquido pontual ≤ 0 ("não é mais positivo");
- prazo: du até o vencimento ≤ N; tempo: pregões sem hedge ≥ N;
- meta: P&L ≥ f × esperado; stop: P&L ≤ −f × perda máxima;
- provento: data ex em (último pregão, último pregão + N du].
Unidades da §5.1: vol decimal, delta em ações, dinheiro em R$ (float só para comparar; o banco
guarda `Decimal`).
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from vollab.quant.edge import Direction, Premium


class RuleState(StrEnum):
    OK = "ok"
    TRIGGERED = "triggered"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


RULE_KIND = {
    "hedge_band": "hedge",
    "hedge_time": "hedge",
    "exit_edge": "exit",
    "exit_dte": "exit",
    "exit_profit": "exit",
    "exit_stop": "exit",
    "roll_suggested": "roll",
    "limit_stress": "limit",
    "limit_vega": "limit",
    "limit_underlying": "limit",
    "limit_expiry": "limit",
    "dividend_upcoming": "dividend",
    "strike_adjustment_pending": "dividend",
}

# Nome do limite em `quant.risk.evaluate_limits` → regra do alerta.
LIMIT_RULES = {
    "stress_loss": "limit_stress",
    "vega_total": "limit_vega",
    "underlying_concentration": "limit_underlying",
    "expiry_concentration": "limit_expiry",
}


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule: str
    state: RuleState
    scope_key: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    reason: str | None = None

    @property
    def kind(self) -> str:
        return RULE_KIND[self.rule]

    @property
    def triggered(self) -> bool:
        return self.state is RuleState.TRIGGERED


# --- Hedge (RN-GES-01) -----------------------------------------------------------------------------


def shares_to_band(delta_shares: float, half_width: float) -> int:
    """Ações a negociar para levar o delta **até a borda** (H1), arredondadas para cima em módulo
    (o delta resultante fica na borda ou dentro). Zero quando já está dentro ou na borda."""
    if half_width < 0:
        raise ValueError("shares_to_band: meia-largura não negativa.")
    if delta_shares > half_width:
        return -math.ceil(delta_shares - half_width - 1e-9)
    if delta_shares < -half_width:
        return math.ceil(-half_width - delta_shares - 1e-9)
    return 0


def hedge_band(delta_shares: float | None, half_width: float) -> RuleResult:
    if delta_shares is None:
        return RuleResult("hedge_band", RuleState.UNAVAILABLE, reason="sem marcação D-1")
    details = {
        "delta_shares": delta_shares,
        "half_width_shares": half_width,
        "adjust_shares": shares_to_band(delta_shares, half_width),
        "calibrated": False,
    }
    state = RuleState.TRIGGERED if abs(delta_shares) > half_width else RuleState.OK
    return RuleResult("hedge_band", state, details=details)


def hedge_time(bd_since_last: int | None, interval_bd: int | None, delta_shares: float | None) -> RuleResult:
    if interval_bd is None:
        return RuleResult("hedge_time", RuleState.DISABLED)
    if bd_since_last is None or delta_shares is None:
        return RuleResult("hedge_time", RuleState.UNAVAILABLE, reason="sem marcação D-1")
    details = {"bd_since_last_hedge": bd_since_last, "interval_bd": interval_bd, "delta_shares": delta_shares}
    fire = bd_since_last >= interval_bd and abs(delta_shares) > 1e-9
    return RuleResult("hedge_time", RuleState.TRIGGERED if fire else RuleState.OK, details=details)


# --- Saída (RN-GES-02/03) --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionEdge:
    """Edge relativo líquido da posição aberta na direção dela, com intervalo (herdado de σ̂)."""

    value: float | None  # None: compra em que o hedge consome todo o edge
    ci_low: float | None
    ci_high: float | None
    premium: Premium
    sigma: float
    cost_hold: float | None  # pontos de vol (decimal); None = compra inviável pelo hedge
    cost_close: float


def position_edge(
    p: Premium, *, sigma: float, direction: Direction, cost_hold: float | None, cost_close: float
) -> PositionEdge:
    """Venda: (p − c)/σ̂; compra: (−p − c)/σ̂, com c = custo de manter (hedge) + custo de fechar."""
    if sigma <= 0 or cost_close < 0 or (cost_hold is not None and cost_hold < 0):
        raise ValueError("position_edge: σ̂ positiva e custos não negativos.")
    if cost_hold is None:
        return PositionEdge(None, None, None, p, sigma, None, cost_close)
    c = cost_hold + cost_close
    if direction is Direction.SELL:
        vals = ((p.value - c), (p.ci_low - c), (p.ci_high - c))
    else:
        vals = ((-p.value - c), (-p.ci_high - c), (-p.ci_low - c))
    v, lo, hi = (x / sigma for x in vals)
    return PositionEdge(v, lo, hi, p, sigma, cost_hold, cost_close)


def exit_edge(edge: PositionEdge | None, reason: str | None = None) -> RuleResult:
    if edge is None:
        return RuleResult("exit_edge", RuleState.UNAVAILABLE, reason=reason or "sem insumos para o edge")
    details: dict[str, Any] = {
        "net_relative_edge": edge.value,
        "ci_low": edge.ci_low,
        "ci_high": edge.ci_high,
        "premium": edge.premium.value,
        "sigma": edge.sigma,
        "cost_hold_vol_pts": edge.cost_hold,
        "cost_close_vol_pts": edge.cost_close,
    }
    if edge.value is None:
        return RuleResult(
            "exit_edge",
            RuleState.TRIGGERED,
            details=details,
            reason="compra de vol: o hedge consome todo o edge restante",
        )
    state = RuleState.TRIGGERED if edge.value <= 0 else RuleState.OK
    return RuleResult("exit_edge", state, details=details, reason=reason)


def exit_dte(days_to_expiry_bd: int | None, max_bd: int | None) -> RuleResult:
    if max_bd is None:
        return RuleResult("exit_dte", RuleState.DISABLED)
    if days_to_expiry_bd is None:
        return RuleResult("exit_dte", RuleState.UNAVAILABLE, reason="sem pernas de opção abertas")
    details = {"days_to_expiry_bd": days_to_expiry_bd, "max_bd": max_bd}
    state = RuleState.TRIGGERED if days_to_expiry_bd <= max_bd else RuleState.OK
    return RuleResult("exit_dte", state, details=details)


def exit_profit(pnl_brl: float | None, expected_brl: float | None, fraction: float | None) -> RuleResult:
    if fraction is None:
        return RuleResult("exit_profit", RuleState.DISABLED)
    if pnl_brl is None:
        return RuleResult("exit_profit", RuleState.UNAVAILABLE, reason="sem atribuição de P&L")
    if expected_brl is None or expected_brl <= 0:
        return RuleResult(
            "exit_profit", RuleState.UNAVAILABLE, reason="P&L esperado na entrada ausente ou ≤ 0"
        )
    target = fraction * expected_brl
    details = {"pnl_brl": pnl_brl, "target_brl": target, "fraction": fraction, "calibrated": False}
    return RuleResult(
        "exit_profit", RuleState.TRIGGERED if pnl_brl >= target else RuleState.OK, details=details
    )


def exit_stop(pnl_brl: float | None, max_loss_brl: float | None, fraction: float | None) -> RuleResult:
    """`max_loss_brl` = perda máxima da posição (L por lote do retrato × lotes)."""
    if fraction is None:
        return RuleResult("exit_stop", RuleState.DISABLED)
    if pnl_brl is None:
        return RuleResult("exit_stop", RuleState.UNAVAILABLE, reason="sem atribuição de P&L")
    if max_loss_brl is None or max_loss_brl <= 0:
        return RuleResult("exit_stop", RuleState.UNAVAILABLE, reason="perda máxima do retrato ausente")
    stop = -fraction * max_loss_brl
    details = {"pnl_brl": pnl_brl, "stop_brl": stop, "fraction": fraction, "calibrated": False}
    return RuleResult("exit_stop", RuleState.TRIGGERED if pnl_brl <= stop else RuleState.OK, details=details)


# --- Rolagem (RN-GES-04) ---------------------------------------------------------------------------


def roll_expiry(expiries: Iterable[date], days_bd: Callable[[date], int], min_bd: int) -> date | None:
    """Primeiro vencimento com ≥ `min_bd` du; None se não houver."""
    for e in sorted(expiries):
        if days_bd(e) >= min_bd:
            return e
    return None


# --- Proventos (RN-GES-06, RS-07) ------------------------------------------------------------------


def in_dividend_window(ex_date: date, as_of: date, window_end: date) -> bool:
    """Data ex em (as_of, window_end]: ainda não aconteceu e cai na antecedência configurada."""
    return as_of < ex_date <= window_end


# --- Ciclo de vida (RN-GES-07) ---------------------------------------------------------------------

Key = tuple[str, int | None, str]  # (regra, posição, escopo)


@dataclass(frozen=True, slots=True)
class OpenAlert:
    id: int
    key: Key


@dataclass(frozen=True, slots=True)
class Plan:
    create: list[Key]
    update: list[tuple[int, Key]]
    resolve: list[int]  # resolvidos automaticamente (condição sumiu)
    release: list[Key]  # chaves cujo alerta resolvido pelo usuário deixa de segurar a reabertura


def reconcile(
    open_alerts: Sequence[OpenAlert],
    firing: Iterable[Key],
    held: Iterable[Key],
    evaluated: Callable[[Key], bool],
) -> Plan:
    """Compara os alertas não resolvidos com as condições que valem agora.

    - `firing`: chaves com a condição valendo; `held`: chaves com um alerta resolvido pelo usuário
      que ainda segura a reabertura (`persisting`).
    - `evaluated(key)`: a regra da chave foi avaliada nesta rodada (uma posição sem marcação não
      resolve os alertas dela por falta de dado).
    """
    firing_set = set(firing)
    held_set = set(held)
    by_key = {a.key: a for a in open_alerts}
    create = sorted((k for k in firing_set if k not in by_key and k not in held_set), key=_sort_key)
    update = sorted(((a.id, a.key) for a in open_alerts if a.key in firing_set), key=lambda x: x[0])
    resolve = sorted(a.id for a in open_alerts if a.key not in firing_set and evaluated(a.key))
    release = sorted((k for k in held_set if k not in firing_set and evaluated(k)), key=_sort_key)
    return Plan(create, update, resolve, release)


def _sort_key(k: Key) -> tuple[str, int, str]:
    return (k[0], k[1] if k[1] is not None else 0, k[2])
