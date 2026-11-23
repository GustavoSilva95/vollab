"""Custos estimados do edge (PRD 1.8 §5.6.1; RN-CST-01..03, RN-EDG-04).

Puro, sem I/O (PRD §4). Unidades do PRD §5.1: vol e custos em pontos de vol em **decimal**
(0,01 = 1 ponto), dinheiro em BRL (float aqui: é estimativa, nunca vai para colunas de dinheiro),
tempo em anos úteis.

- Spread de uma série: mediana de |Pᵢ − Pᵢ₋₁| entre negócios consecutivos com preço diferente (o
  vaivém entre compra e venda; "execução × negócio anterior", referência cap. 6), com piso.
- Custo do hedge: Leland (eqs. 6.7–6.8 da referência, igual ao `leland_vol` da §6).
- Custo das opções: straddle ATM teórico (strike = forward), ida e volta, convertido em pontos de vol
  pela vega do straddle.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import ArrayLike

from vollab.quant.pricing import bs_greeks


class Band(StrEnum):
    LOW = "low"  # K/F abaixo do limite inferior
    ATM = "atm"
    HIGH = "high"  # K/F acima do limite superior
    UNDERLYING = "underlying"


OPTION_BANDS = (Band.LOW, Band.ATM, Band.HIGH)


def moneyness_band(k_over_f: float, bands: tuple[float, float]) -> Band:
    lo, hi = bands
    if k_over_f < lo:
        return Band.LOW
    if k_over_f > hi:
        return Band.HIGH
    return Band.ATM


# --- Spread de uma série (RN-CST-03) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeriesSpread:
    spread_brl: float  # já com o piso
    relative: float  # spread ÷ mediana do preço no dia
    trades: int
    price_changes: int
    floored: bool


def series_spread(prices: ArrayLike, *, floor_brl: float, min_trades: int) -> SeriesSpread | None:
    """Spread estimado de uma série no dia, a partir dos negócios em ordem (horário, identificador).

    None abaixo de `min_trades` ou com preço não positivo. Sem nenhuma troca de preço o spread é o
    piso (o mercado negociou sempre no mesmo preço: não há como medir mais que um tick)."""
    p = np.asarray(prices, dtype=np.float64)
    if p.size < min_trades or p.size < 2 or not np.all(np.isfinite(p)) or np.any(p <= 0):
        return None
    d = np.abs(np.diff(p))
    changes = d[d > 0]
    raw = float(np.median(changes)) if changes.size else 0.0
    spread = max(raw, floor_brl)
    mid = float(np.median(p))
    return SeriesSpread(
        spread_brl=spread,
        relative=spread / mid,
        trades=int(p.size),
        price_changes=int(changes.size),
        floored=raw < floor_brl,
    )


def quoted_relative_spread(best_bid: float, best_ask: float, avg_price: float) -> float | None:
    """Spread de fechamento do COTAHIST: (melhor venda − melhor compra) ÷ preço médio. None sem as
    duas pontas válidas."""
    if best_bid <= 0 or best_ask <= best_bid or avg_price <= 0:
        return None
    return (best_ask - best_bid) / avg_price


@dataclass(frozen=True, slots=True)
class BandDay:
    """Agregado de um pregão e faixa (linha de `option_spread_estimates`)."""

    n_series: int
    n_trades: int
    rel_median: float | None
    rel_p75: float | None
    quoted_rel_median: float | None


def aggregate_band(spreads: Sequence[SeriesSpread], quoted: Sequence[float]) -> BandDay:
    med: float | None
    p75: float | None
    if spreads:
        rel = np.array([s.relative for s in spreads])
        med, p75 = float(np.median(rel)), float(np.quantile(rel, 0.75))
    else:
        med = p75 = None
    q = float(np.median(quoted)) if quoted else None
    return BandDay(len(spreads), sum(s.trades for s in spreads), med, p75, q)


@dataclass(frozen=True, slots=True)
class SpreadEstimate:
    """Spread relativo usado no edge, numa janela de pregões."""

    central: float
    conservative: float  # RN-EDG-04: o que entra no semáforo
    days: int
    n_series: int  # soma no período
    quoted: float | None  # conferência: spread de fechamento do COTAHIST (fora do custo, PRD 1.8.1)


def spread_estimate(days: Sequence[BandDay]) -> SpreadEstimate | None:
    """Central = mediana das medianas diárias; conservador = mediana dos p75 diários. O spread de
    fechamento do COTAHIST é só conferência (PRD 1.8.1: as ofertas após o fechamento vinham velhas ou
    fora de mercado nas fixtures, 10× o spread dos negócios). None se nenhum pregão tiver estimativa."""
    used = [d for d in days if d.rel_median is not None and d.rel_p75 is not None]
    if not used:
        return None
    central = float(np.median([d.rel_median for d in used]))
    p75 = float(np.median([d.rel_p75 for d in used]))
    quoted = [d.quoted_rel_median for d in days if d.quoted_rel_median is not None]
    return SpreadEstimate(
        central,
        max(p75, central),
        len(used),
        sum(d.n_series for d in used),
        float(np.median(quoted)) if quoted else None,
    )


# --- Hedge (Leland, eqs. 6.7–6.8) --------------------------------------------------------------


def leland_vol(sigma: float, half_spread: float, dt: float, *, long: bool) -> float | None:
    """σ ajustado de Leland. `half_spread` = custo proporcional por operação (λ); `dt` em anos.

    Comprado: σ·√(1 − a); vendido: σ·√(1 + a), a = (λ/σ)·√(8/(πΔt)). Comprado com a ≥ 1: o hedge
    consome toda a vol (None)."""
    if sigma <= 0 or dt <= 0 or half_spread < 0:
        raise ValueError("leland_vol: σ e Δt positivos, λ ≥ 0.")
    a = (half_spread / sigma) * math.sqrt(8.0 / (math.pi * dt))
    if long:
        return sigma * math.sqrt(1.0 - a) if a < 1.0 else None
    return sigma * math.sqrt(1.0 + a)


@dataclass(frozen=True, slots=True)
class HedgeCost:
    sell: float  # pontos de vol (decimal) que o hedge consome vendido em vol
    buy: float | None  # None: o hedge consome todo o edge de compra
    half_spread: float  # λ usado (meio spread relativo + taxa)


def hedge_cost(sigma: float, *, underlying_rel_spread: float, fee_rate: float, interval_bd: int) -> HedgeCost:
    lam = underlying_rel_spread / 2.0 + fee_rate
    dt = interval_bd / 252.0
    short = leland_vol(sigma, lam, dt, long=False)
    long = leland_vol(sigma, lam, dt, long=True)
    if short is None:  # vendido sempre tem solução; só para o mypy
        raise ValueError("leland_vol vendido sem solução.")
    return HedgeCost(sell=short - sigma, buy=None if long is None else sigma - long, half_spread=lam)


# --- Opções: straddle ATM de referência -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StraddleCost:
    premium_brl: float  # por straddle (uma call + uma put)
    vega_brl: float  # por 1,00 de vol, por straddle
    spread_brl: float  # ida e volta
    fees_brl: float
    brokerage_brl: float

    @property
    def total_brl(self) -> float:
        return self.spread_brl + self.fees_brl + self.brokerage_brl

    @property
    def vol_points(self) -> float:
        return self.total_brl / self.vega_brl


def straddle_cost(
    *,
    spot: float,
    t: float,
    rate_c: float,
    iv: float,
    pv_div: float,
    option_rel_spread: float,
    fee_rate: float,
    brokerage_rate: float,
    brokerage_per_order_brl: float,
    reference_contracts: int,
) -> StraddleCost:
    """Straddle ATM teórico (strike = forward), precificado por BS à IV. Ida e volta em cada perna:
    meio spread na entrada + meio na saída (= um spread), taxas e corretagem nas duas pontas; a
    corretagem fixa (4 ordens) é rateada pelas opções da estrutura de referência."""
    if t <= 0 or iv <= 0 or spot - pv_div <= 0:
        raise ValueError("straddle_cost: t, IV e S* positivos.")
    forward = (spot - pv_div) * math.exp(rate_c * t)
    g = bs_greeks(
        np.array([spot, spot]),
        np.array([forward, forward]),
        t,
        rate_c,
        iv,
        np.array([True, False]),
        pv_div,
    )
    premium = float(g.price.sum())
    vega = float(g.vega_per_point.sum()) * 100.0
    return StraddleCost(
        premium_brl=premium,
        vega_brl=vega,
        spread_brl=option_rel_spread * premium,
        fees_brl=2.0 * fee_rate * premium,
        brokerage_brl=2.0 * brokerage_rate * premium + 4.0 * brokerage_per_order_brl / reference_contracts,
    )
