"""Marcação D-1 e atribuição diária de P&L (PRD 1.10 §5.9; BRD 1.7 RF-DIA-04, CS-04, RS-06).

Puro, sem I/O. Expansão de Taylor da eq. 1.4 da referência, com os Greeks da marcação de *t*−1 e as
quantidades do fechamento de *t*−1:

- ΔS* = Sₜ + Dₜ − Sₜ₋₁ (retorno ajustado por provento, RN-VOL-07);
- delta = Δₜ₋₁·ΔS*; gamma = ½·Γₜ₋₁·(ΔS*)²; theta = Θₜ₋₁·n_du (Θ por dia útil);
- vega = Σ pernas 𝒱ₜ₋₁·(IVₜ − IVₜ₋₁)/0,01 (vega por ponto de vol);
- P&L de mercado = Σ qₜ₋₁·(mₜ − mₜ₋₁) + q_açãoₜ₋₁·Dₜ; resíduo = mercado − (delta+gamma+theta+vega).

Execução e custos (fora do resíduo): para cada transação do dia, q·(mₜ − preço) − custos. Dinheiro em
`Decimal` (as marcações são gravadas com 6 casas): a soma de mercado + execução ao longo da vida é
exatamente o P&L pelos fluxos de caixa (invariante testado).
"""

import bisect
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

import numpy as np

from vollab.quant.journal import Transaction
from vollab.quant.pricing import BUSINESS_DAYS_PER_YEAR, bs_greeks

MICRO = Decimal("0.000001")
ZERO = Decimal(0)


def dec(value: float) -> Decimal:
    """float → Decimal com 6 casas (o mesmo arredondamento das colunas NUMERIC(18,6))."""
    return Decimal(repr(float(value))).quantize(MICRO, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class LegQuote:
    """Insumos da marcação de uma perna num pregão."""

    code: str
    is_call: bool
    strike_eff: float  # strike efetivo (com proventos protegidos já descontados)
    days_to_expiry_bd: float  # 0 = vence no pregão (valor intrínseco); fração só em testes
    iv: float | None  # IV usada (referência, do fechamento ou a anterior)
    origin: str  # observed | approximate | stale
    price_override: float | None = None  # preço observado (fechamento) quando a origem é approximate


@dataclass(frozen=True, slots=True)
class LegMark:
    code: str
    quantity: int
    price: Decimal
    iv: float | None
    origin: str  # observed | approximate | stale | expired
    delta: float
    gamma: float
    vega_per_point: float
    theta_per_bd: float


@dataclass(slots=True)
class DayMark:
    """Marcação de uma posição num pregão (quantidades do fechamento)."""

    day: date
    spot: Decimal
    stock_qty: int
    legs: dict[str, LegMark] = field(default_factory=dict)

    @property
    def stale(self) -> bool:
        return any(m.origin == "stale" for m in self.legs.values() if m.quantity != 0)

    def value(self, quantities: Mapping[str, int], stock_code: str) -> Decimal:
        total = Decimal(quantities.get(stock_code, 0)) * self.spot
        for code, leg in self.legs.items():
            total += Decimal(quantities.get(code, 0)) * leg.price
        return total

    def greeks(self) -> tuple[float, float, float, float]:
        """Delta (ações, com a ação), gamma, vega por ponto e theta por dia útil da posição."""
        d = float(self.stock_qty)
        g = v = th = 0.0
        for leg in self.legs.values():
            d += leg.quantity * leg.delta
            g += leg.quantity * leg.gamma
            v += leg.quantity * leg.vega_per_point
            th += leg.quantity * leg.theta_per_bd
        return d, g, v, th


def intrinsic(spot: float, strike: float, is_call: bool) -> float:
    return max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)


def mark_legs(
    spot: float,
    rate_c: float,
    pv_div: float,
    quotes: Sequence[LegQuote],
    quantities: Mapping[str, int],
) -> dict[str, LegMark]:
    """Preço e Greeks de cada perna (BS europeu com dividendos discretos, PRD §5.1).

    No vencimento (0 du) e depois dele vale o intrínseco, sem Greeks. Origem `approximate` usa o
    preço observado (fechamento) e a IV extraída dele; as demais usam BS com a IV."""
    out: dict[str, LegMark] = {}
    live = [q for q in quotes if q.days_to_expiry_bd > 0 and q.iv is not None]
    if live:
        g = bs_greeks(
            spot,
            np.array([q.strike_eff for q in live]),
            np.array([q.days_to_expiry_bd / BUSINESS_DAYS_PER_YEAR for q in live]),
            rate_c,
            np.array([q.iv for q in live]),
            np.array([q.is_call for q in live]),
            pv_div,
        )
        for i, q in enumerate(live):
            price = q.price_override if q.price_override is not None else float(g.price[i])
            out[q.code] = LegMark(
                code=q.code,
                quantity=quantities.get(q.code, 0),
                price=dec(price),
                iv=q.iv,
                origin=q.origin,
                delta=float(g.delta[i]),
                gamma=float(g.gamma[i]),
                vega_per_point=float(g.vega_per_point[i]),
                theta_per_bd=float(g.theta_per_bd[i]),
            )
    for q in quotes:
        if q.code in out:
            continue
        if q.days_to_expiry_bd > 0:  # sem IV: não deveria chegar aqui (o chamador usa a anterior)
            raise ValueError(f"mark_legs: {q.code} sem IV antes do vencimento.")
        out[q.code] = LegMark(
            code=q.code,
            quantity=quantities.get(q.code, 0),
            price=dec(intrinsic(spot, q.strike_eff, q.is_call)),
            iv=q.iv,
            origin="expired",
            delta=0.0,
            gamma=0.0,
            vega_per_point=0.0,
            theta_per_bd=0.0,
        )
    return out


@dataclass(frozen=True, slots=True)
class AttributionDay:
    day: date
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    market: Decimal
    residual: Decimal
    execution: Decimal
    stale: bool

    @property
    def explained_abs(self) -> Decimal:
        return abs(self.delta) + abs(self.gamma) + abs(self.theta) + abs(self.vega)

    @property
    def total(self) -> Decimal:
        return self.market + self.execution


def market_terms(
    prev: DayMark,
    curr: DayMark,
    *,
    stock_code: str,
    prev_quantities: Mapping[str, int],
    dividend: Decimal,
    days_bd: float,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """(delta, gamma, theta, vega, mercado) entre dois pregões consecutivos com marcação."""
    ds = float(curr.spot + dividend - prev.spot)
    d, g, _, th = prev.greeks()
    # As quantidades de t−1 são as da marcação de t−1 (prev.legs[*].quantity e prev.stock_qty).
    delta = d * ds
    gamma = 0.5 * g * ds * ds
    theta = th * days_bd
    vega = 0.0
    for code, leg in prev.legs.items():
        if leg.quantity == 0:
            continue
        now = curr.legs.get(code)
        if now is None or now.iv is None or leg.iv is None or now.origin == "expired":
            continue
        vega += leg.quantity * leg.vega_per_point * (now.iv - leg.iv) / 0.01
    market = Decimal(prev_quantities.get(stock_code, 0)) * (curr.spot - prev.spot + dividend)
    for code, q in prev_quantities.items():
        if code == stock_code or q == 0:
            continue
        old, new = prev.legs.get(code), curr.legs.get(code)
        if old is None or new is None:
            raise ValueError(f"market_terms: {code} sem marcação em um dos pregões.")
        market += Decimal(q) * (new.price - old.price)
    return dec(delta), dec(gamma), dec(theta), dec(vega), market


def execution_line(curr: DayMark, txs: Iterable[Transaction], *, stock_code: str) -> Decimal:
    """Σ q·(marcação do dia − preço executado) − custos, nas transações executadas no pregão."""
    total = ZERO
    for tx in txs:
        if tx.instrument == stock_code:
            mark = curr.spot
        else:
            leg = curr.legs.get(tx.instrument)
            if leg is None:
                raise ValueError(f"execution_line: {tx.instrument} sem marcação no pregão.")
            mark = leg.price
        total += Decimal(tx.quantity) * (mark - tx.price) - tx.costs
    return total


def attribute(
    prev: DayMark | None,
    curr: DayMark,
    *,
    stock_code: str,
    prev_quantities: Mapping[str, int],
    dividend: Decimal,
    days_bd: float,
    txs: Iterable[Transaction],
) -> AttributionDay:
    execution = execution_line(curr, txs, stock_code=stock_code)
    if prev is None:  # dia da entrada: só execução e custos
        return AttributionDay(curr.day, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO, execution, curr.stale)
    delta, gamma, theta, vega, market = market_terms(
        prev, curr, stock_code=stock_code, prev_quantities=prev_quantities, dividend=dividend, days_bd=days_bd
    )
    residual = market - (delta + gamma + theta + vega)
    return AttributionDay(
        curr.day, delta, gamma, theta, vega, market, residual, execution, curr.stale or prev.stale
    )


def quantities_of(mark: DayMark, stock_code: str) -> dict[str, int]:
    out = {code: leg.quantity for code, leg in mark.legs.items()}
    out[stock_code] = mark.stock_qty
    return out


def assign_days(txs: Iterable[Transaction], days: Sequence[date]) -> dict[date, list[Transaction]]:
    """Cada transação vai para o primeiro pregão marcado ≥ a data de execução (lançamento num dia sem
    pregão conta no pregão seguinte). Transações depois da última marcação ficam de fora."""
    out: dict[date, list[Transaction]] = {}
    for tx in txs:
        i = bisect.bisect_left(days, tx.day)
        if i < len(days):
            out.setdefault(days[i], []).append(tx)
    return out


def attribute_life(
    marks: Sequence[DayMark],
    txs: Iterable[Transaction],
    *,
    stock_code: str,
    dividends: Mapping[date, Decimal],
    days_between: Callable[[date, date], float],
) -> list[AttributionDay]:
    """Atribuição de todos os pregões marcados, em ordem. O primeiro só tem execução e custos."""
    days = [m.day for m in marks]
    by_day = assign_days(txs, days)
    out: list[AttributionDay] = []
    prev: DayMark | None = None
    for m in marks:
        prev_q = quantities_of(prev, stock_code) if prev is not None else {}
        out.append(
            attribute(
                prev,
                m,
                stock_code=stock_code,
                prev_quantities=prev_q,
                dividend=dividends.get(m.day, ZERO),
                days_bd=days_between(prev.day, m.day) if prev is not None else 0,
                txs=by_day.get(m.day, []),
            )
        )
        prev = m
    return out


def cs04_ratio(days: Iterable[AttributionDay]) -> float | None:
    """Σ|resíduo| ÷ Σ(|delta|+|gamma|+|theta|+|vega|) ao longo da vida (CS-04). None sem base."""
    res = expl = ZERO
    for a in days:
        res += abs(a.residual)
        expl += a.explained_abs
    return None if expl == 0 else float(res / expl)


def error_flag(day: AttributionDay, *, max_ratio: float, min_brl: float) -> bool:
    """Sinal de possível erro de lançamento (RS-06): resíduo acima da fração **e** do valor mínimo
    (comparações estritas; igual ao limite não dispara)."""
    res = abs(day.residual)
    if res <= Decimal(repr(min_brl)):
        return False
    return float(res) > max_ratio * float(day.explained_abs)


def delta_band_state(delta_shares: float, half_width: float) -> str:
    """Indicador de banda (fluxo 3): fora se |Δ| > meia-largura (estrito)."""
    if not math.isfinite(delta_shares):
        return "unavailable"
    return "outside" if abs(delta_shares) > half_width else "inside"
