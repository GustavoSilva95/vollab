"""Simulador de estruturas (PRD 1.9 §5.8; BRD 1.6 RF-SIM-01..05, QA-10, QA-11 parcial).

Puro, sem I/O (PRD §4). Unidades do PRD §5.1: vol decimal anualizada em base 252, tempo em anos
úteis, taxa **contínua** (já convertida da Selic), dinheiro em BRL (float: são estimativas; nunca vão
para colunas de dinheiro). Tudo é calculado **por unidade** da estrutura (uma opção por perna; ação na
mesma quantidade) e multiplicado pelo tamanho do lote: a banda de delta também escala com o tamanho,
então o P&L por lote = lote × P&L por unidade.

- Distribuição (QA-10): bootstrap i.i.d. dos retornos log diários reais, com média zero e reescalados
  para a vol prevista σ̂ (desvio com divisor n, coerente com a eq. 2.1b).
- Hedge (QA-11, H1 e H5 da referência): delta à IV de entrada; fora da banda, ajusta só até a borda
  (`rehedge` da referência, §6). Venda coberta: sem ajustes (a ação é a cobertura fixa).
- IV constante na vida da simulação; o risco de vega fica com o stress (`stress_losses`).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import ArrayLike, NDArray

from vollab.quant.edge import Direction
from vollab.quant.pricing import BUSINESS_DAYS_PER_YEAR, bs_delta, bs_greeks, bs_price

FloatArray = NDArray[np.float64]


class Structure(StrEnum):
    SHORT_STRADDLE = "short_straddle"
    SHORT_STRANGLE = "short_strangle"
    COVERED_CALL = "covered_call"
    LONG_STRADDLE = "long_straddle"
    LONG_STRANGLE = "long_strangle"


STRUCTURE_DIRECTION: dict[Structure, Direction] = {
    Structure.SHORT_STRADDLE: Direction.SELL,
    Structure.SHORT_STRANGLE: Direction.SELL,
    Structure.COVERED_CALL: Direction.SELL,
    Structure.LONG_STRADDLE: Direction.BUY,
    Structure.LONG_STRANGLE: Direction.BUY,
}

# Venda coberta: a ação fica fixa (um hedge dinâmico a transformaria em call vendida hedgeada).
DYNAMIC_HEDGE: dict[Structure, bool] = {s: s is not Structure.COVERED_CALL for s in Structure}


@dataclass(frozen=True, slots=True)
class Leg:
    """Perna de opção: quantidade por unidade (+1 comprada, −1 vendida), strike efetivo e IV."""

    is_call: bool
    strike: float
    quantity: int
    iv: float
    price: float  # preço de entrada por opção (BRL)
    entry_cost_rate: float  # custo proporcional na entrada: meio spread + taxa + corretagem (decimal)
    entry_cost_fixed: float = 0.0  # corretagem fixa por opção (BRL)


def stock_quantity(structure: Structure) -> int:
    """Ação na estrutura por unidade (venda coberta: uma ação por call vendida)."""
    return 1 if structure is Structure.COVERED_CALL else 0


def validate_legs(structure: Structure, legs: Sequence[Leg]) -> str | None:
    """Motivo se as pernas não formam a estrutura (RF-SIM-01); None se formam."""
    calls = [leg for leg in legs if leg.is_call]
    puts = [leg for leg in legs if not leg.is_call]
    sign = -1 if STRUCTURE_DIRECTION[structure] is Direction.SELL else 1
    if any(leg.quantity != sign for leg in legs):
        return "quantidade das pernas incompatível com a estrutura"
    if structure is Structure.COVERED_CALL:
        return None if len(calls) == 1 and not puts else "venda coberta exige uma call"
    if len(calls) != 1 or len(puts) != 1:
        return "straddle e strangle exigem uma call e uma put"
    k_put, k_call = puts[0].strike, calls[0].strike
    if structure in (Structure.SHORT_STRADDLE, Structure.LONG_STRADDLE):
        return (
            None if math.isclose(k_put, k_call, rel_tol=0, abs_tol=1e-9) else "straddle exige o mesmo strike"
        )
    return None if k_put < k_call else "strangle exige strike da put menor que o da call"


# --- Bootstrap reescalado (QA-10) --------------------------------------------------------------


def rescale_returns(returns: ArrayLike, sigma_annual: float) -> FloatArray:
    """zᵢ = (rᵢ − r̄)·σ̂_d/sₙ, sₙ com divisor n. A amostra devolvida tem média 0 e desvio exatamente
    σ̂_d = σ̂/√252; a forma (caudas, assimetria) é a do histórico."""
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 2 or sigma_annual <= 0:
        raise ValueError("rescale_returns: ≥ 2 retornos finitos e σ̂ positivo.")
    centered = r - r.mean()
    s_n = math.sqrt(float(np.mean(centered * centered)))
    if s_n <= 0:
        raise ValueError("rescale_returns: retornos sem variação.")
    return centered * (sigma_annual / math.sqrt(BUSINESS_DAYS_PER_YEAR) / s_n)


def rehedge(current_delta: FloatArray, half_width: float) -> FloatArray:
    """Regra de banda centrada em zero (referência §6, `rehedge`): fora da banda, ajusta só até a
    borda. Devolve a quantidade de ações a negociar (positivo = comprar)."""
    hi, lo = half_width, -half_width
    return np.where(
        current_delta > hi, hi - current_delta, np.where(current_delta < lo, lo - current_delta, 0.0)
    )


@dataclass(frozen=True, slots=True)
class Market:
    spot: float
    rate_c: float  # taxa contínua anual
    days_bd: int  # pregões até o vencimento
    # Proventos com data ex na vida da opção: (índice do pregão 1..days_bd, valor por ação).
    dividends: tuple[tuple[int, float], ...] = ()

    def pv_dividends(self, step: int) -> float:
        """VP, no pregão `step`, dos proventos com data ex depois dele."""
        return sum(
            amount * math.exp(-self.rate_c * (i - step) / BUSINESS_DAYS_PER_YEAR)
            for i, amount in self.dividends
            if i > step
        )


@dataclass(frozen=True, slots=True)
class HedgeRule:
    dynamic: bool
    half_width: float  # meia-largura da banda em ações por unidade (= b por opção)
    cost_rate: float  # λ do ativo-objeto: meio spread + taxa (decimal)


PATH_BLOCK = 5_000  # caminhos por bloco: pico de memória ~10 MB por 100 pregões


@dataclass(frozen=True, slots=True)
class PathResult:
    """P&L por unidade em cada caminho, com os componentes usados nos resumos."""

    pnl: FloatArray
    rehedges: NDArray[np.int64]
    hedge_cost: FloatArray
    entry_cost: float


def simulate_paths(
    legs: Sequence[Leg],
    stock_qty: int,
    market: Market,
    rule: HedgeRule,
    scaled_returns: ArrayLike,
    *,
    paths: int,
    seed: int,
) -> PathResult:
    """Caminhos do ativo por bootstrap (sorteio com reposição) e P&L da estrutura até o vencimento.

    Sₜ₊₁ = Sₜ·exp(zₜ − σ̂_d²/2 + r_d) − Dₜ₊₁. Caixa remunerado à taxa contínua; proventos pagos à ação
    em carteira. No vencimento as opções valem o intrínseco e a ação resultante (hedge + exercício) é
    zerada pagando λ. Determinístico para a mesma semente."""
    z = np.asarray(scaled_returns, dtype=np.float64)
    h = market.days_bd
    if h < 1 or paths < 1 or z.size == 0:
        raise ValueError("simulate_paths: prazo, caminhos e amostra positivos.")
    rng = np.random.default_rng(seed)
    sigma_d2 = float(np.mean(z * z))
    r_d = market.rate_c / BUSINESS_DAYS_PER_YEAR
    growth = math.exp(r_d)
    divs = dict(market.dividends)
    pv_by_step = [market.pv_dividends(step) for step in range(h)]

    k = np.array([leg.strike for leg in legs])
    q = np.array([leg.quantity for leg in legs], dtype=np.float64)
    call = np.array([leg.is_call for leg in legs])
    iv = np.array([leg.iv for leg in legs])
    price0 = np.array([leg.price for leg in legs])
    entry_cost = float(
        sum(abs(leg.quantity) * (leg.price * leg.entry_cost_rate + leg.entry_cost_fixed) for leg in legs)
    )

    def options_delta(spot: FloatArray, step: int) -> FloatArray:
        t = (h - step) / BUSINESS_DAYS_PER_YEAR
        return np.asarray(bs_delta(spot[:, None], k, t, market.rate_c, iv, call, pv_by_step[step]) @ q)

    def block(rows: int) -> tuple[FloatArray, NDArray[np.int64], FloatArray]:
        # Sorteio de um bloco de caminhos: blocos de linhas em sequência consomem o mesmo fluxo do
        # gerador que o sorteio único (resultado idêntico), com memória limitada (revisão da Etapa 6, I-1).
        idx = rng.integers(0, z.size, size=(rows, h))
        s = np.full(rows, market.spot)
        cash = np.full(rows, -float(q @ price0) - entry_cost)
        n = -options_delta(s, 0) + stock_qty if rule.dynamic else np.full(rows, float(stock_qty))
        hedge_cost = np.abs(n) * s * rule.cost_rate
        cash -= n * s + hedge_cost
        rehedges = np.zeros(rows, dtype=np.int64)
        for step in range(1, h + 1):
            d = divs.get(step, 0.0)
            s = np.maximum(s * np.exp(z[idx[:, step - 1]] - 0.5 * sigma_d2 + r_d) - d, 1e-8)
            cash = cash * growth + n * d
            if step < h and rule.dynamic:
                trade = rehedge(options_delta(s, step) + n, rule.half_width)
                cost = np.abs(trade) * s * rule.cost_rate
                n = n + trade
                cash -= trade * s + cost
                hedge_cost += cost
                rehedges += trade != 0.0
        intrinsic = np.where(call, np.maximum(s[:, None] - k, 0.0), np.maximum(k - s[:, None], 0.0))
        itm = np.where(call, s[:, None] > k, s[:, None] < k)
        # Ações entregues ou recebidas no exercício: call comprada recebe, put comprada entrega.
        exercised = (itm * np.where(call, 1.0, -1.0)) @ q
        close_cost = np.abs(n + exercised) * s * rule.cost_rate
        hedge_cost += close_cost
        return cash + intrinsic @ q + n * s - close_cost, rehedges, hedge_cost

    parts = [block(min(PATH_BLOCK, paths - start)) for start in range(0, paths, PATH_BLOCK)]
    pnl = np.concatenate([p[0] for p in parts])
    rehedges = np.concatenate([p[1] for p in parts])
    hedge_cost = np.concatenate([p[2] for p in parts])
    return PathResult(pnl=pnl, rehedges=rehedges, hedge_cost=hedge_cost, entry_cost=entry_cost)


# --- Resumo da distribuição (RF-SIM-04/05) ------------------------------------------------------

PERCENTILES = (1, 5, 25, 50, 75, 95, 99)


def expected_shortfall(pnl: ArrayLike, level: float) -> float:
    """ES no nível `level`: média das perdas no pior (1 − level) dos caminhos, como perda positiva
    (negativa quando até o pior grupo lucra). Usa ⌈(1 − level)·N⌉ caminhos."""
    x = np.sort(np.asarray(pnl, dtype=np.float64))
    k = max(1, math.ceil(round((1.0 - level) * x.size, 9)))
    return -float(np.mean(x[:k]))


@dataclass(frozen=True, slots=True)
class Distribution:
    mean: float
    std: float  # divisor n (variância da distribuição simulada, RN-SIZ-02)
    variance: float
    percentiles: dict[int, float]
    es: float
    prob_loss: float
    mean_rehedges: float
    mean_hedge_cost: float
    hist_edges: list[float]
    hist_counts: list[int]


def summarize(result: PathResult, *, lot_size: int, es_level: float, bins: int) -> Distribution:
    """Resumo por lote (BRL)."""
    pnl = result.pnl * lot_size
    counts, edges = np.histogram(pnl, bins=bins)
    var = float(np.var(pnl))
    return Distribution(
        mean=float(np.mean(pnl)),
        std=math.sqrt(var),
        variance=var,
        percentiles={p: float(np.percentile(pnl, p)) for p in PERCENTILES},
        es=expected_shortfall(pnl, es_level),
        prob_loss=float(np.mean(pnl < 0)),
        mean_rehedges=float(np.mean(result.rehedges)),
        mean_hedge_cost=float(np.mean(result.hedge_cost)) * lot_size,
        hist_edges=[float(e) for e in edges],
        hist_counts=[int(c) for c in counts],
    )


def kamal_derman_std(vega_per_point: float, sigma: float, rehedges: int) -> float | None:
    """Eq. 7.7: σ_P/L ≈ √(π/4)·Vega·σ/√N (vega por ponto, σ em pontos). Aproximação (H6)."""
    if rehedges < 1:
        return None
    return math.sqrt(math.pi / 4.0) * abs(vega_per_point) * sigma * 100.0 / math.sqrt(rehedges)


# --- Payoff e Greeks (RF-SIM-02) ----------------------------------------------------------------


def structure_value(
    legs: Sequence[Leg], stock_qty: int, spot: ArrayLike, market: Market, step: int, iv_shift: float = 0.0
) -> FloatArray:
    """Valor das opções + ação por unidade no pregão `step` (vencimento = intrínseco), sem hedge."""
    s = np.asarray(spot, dtype=np.float64)
    h = market.days_bd
    total = stock_qty * s
    for leg in legs:
        if step >= h:
            v = np.maximum(s - leg.strike, 0.0) if leg.is_call else np.maximum(leg.strike - s, 0.0)
        else:
            t = (h - step) / BUSINESS_DAYS_PER_YEAR
            v = bs_price(
                s, leg.strike, t, market.rate_c, leg.iv + iv_shift, leg.is_call, market.pv_dividends(step)
            )
        total = total + leg.quantity * v
    return np.asarray(total, dtype=np.float64)


def entry_value(legs: Sequence[Leg], stock_qty: int, spot: float) -> float:
    return stock_qty * spot + sum(leg.quantity * leg.price for leg in legs)


def payoff_curve(
    legs: Sequence[Leg], stock_qty: int, market: Market, spots: ArrayLike, step: int
) -> FloatArray:
    """P&L por unidade em função de S no pregão `step`, contra os preços de entrada, sem hedge nem
    custos (o gráfico de payoff; custos e hedge entram na distribuição)."""
    return structure_value(legs, stock_qty, spots, market, step) - entry_value(legs, stock_qty, market.spot)


@dataclass(frozen=True, slots=True)
class Greeks:
    """Por unidade: delta em ações, gamma por R$, vega por ponto, theta por dia útil."""

    delta: float
    gamma: float
    vega_per_point: float
    theta_per_bd: float


def structure_greeks(legs: Sequence[Leg], stock_qty: int, market: Market) -> Greeks:
    t = market.days_bd / BUSINESS_DAYS_PER_YEAR
    g = bs_greeks(
        market.spot,
        np.array([leg.strike for leg in legs]),
        t,
        market.rate_c,
        np.array([leg.iv for leg in legs]),
        np.array([leg.is_call for leg in legs]),
        market.pv_dividends(0),
    )
    q = np.array([leg.quantity for leg in legs], dtype=np.float64)
    return Greeks(
        delta=float(g.delta @ q) + stock_qty,
        gamma=float(g.gamma @ q),
        vega_per_point=float(g.vega_per_point @ q),
        theta_per_bd=float(g.theta_per_bd @ q),
    )


def structure_iv(legs: Sequence[Leg], market: Market) -> float:
    """IV da estrutura: média das IVs das pernas ponderada pela vega (absoluta)."""
    t = market.days_bd / BUSINESS_DAYS_PER_YEAR
    g = bs_greeks(
        market.spot,
        np.array([leg.strike for leg in legs]),
        t,
        market.rate_c,
        np.array([leg.iv for leg in legs]),
        np.array([leg.is_call for leg in legs]),
        market.pv_dividends(0),
    )
    w = np.abs(g.vega_per_point)
    if float(w.sum()) <= 0:
        raise ValueError("structure_iv: vega nula.")
    return float(np.dot(w, [leg.iv for leg in legs]) / w.sum())


# --- Stress na entrada (RN-SIZ-03, QA-09) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StressScenario:
    name: str
    spot_shock: float  # relativo (−0,10 = queda de 10%)
    vol_shock: float  # pontos de vol em decimal, somados à IV de todas as pernas


@dataclass(frozen=True, slots=True)
class StressLoss:
    scenario: StressScenario
    loss: float  # por unidade, BRL; positivo = perda


def initial_hedge(legs: Sequence[Leg], stock_qty: int, market: Market, dynamic: bool) -> float:
    """Ações na entrada: hedge até delta zero, ou a ação fixa da venda coberta."""
    if not dynamic:
        return float(stock_qty)
    g = structure_greeks(legs, 0, market)
    return -g.delta + stock_qty


def stress_losses(
    legs: Sequence[Leg],
    stock_qty: int,
    market: Market,
    rule: HedgeRule,
    scenarios: Sequence[StressScenario],
    *,
    exit_cost_rates: Sequence[float],
) -> list[StressLoss]:
    """Choque instantâneo na entrada sobre a estrutura com o hedge inicial, reprecificada por BS e
    zerada pagando `exit_cost_rates` (meio spread + taxas, por perna) e λ na ação. Inclui os custos
    de entrada (a perda é contra o capital antes do trade)."""
    n0 = initial_hedge(legs, stock_qty, market, rule.dynamic)
    entry_cost = sum(
        abs(leg.quantity) * (leg.price * leg.entry_cost_rate + leg.entry_cost_fixed) for leg in legs
    )
    entry_cost += abs(n0) * market.spot * rule.cost_rate
    t = market.days_bd / BUSINESS_DAYS_PER_YEAR
    out = []
    for sc in scenarios:
        s1 = market.spot * (1.0 + sc.spot_shock)
        change = n0 * (s1 - market.spot)
        exit_cost = abs(n0) * s1 * rule.cost_rate
        for leg, rate in zip(legs, exit_cost_rates, strict=True):
            v1 = float(
                bs_price(
                    s1,
                    leg.strike,
                    t,
                    market.rate_c,
                    leg.iv + sc.vol_shock,
                    leg.is_call,
                    market.pv_dividends(0),
                )
            )
            change += leg.quantity * (v1 - leg.price)
            exit_cost += abs(leg.quantity) * (v1 * rate + leg.entry_cost_fixed)
        out.append(StressLoss(sc, -(change - entry_cost - exit_cost)))
    return out
