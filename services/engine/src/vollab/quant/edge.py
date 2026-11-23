"""Prêmio de vol, edge relativo, spread normal e semáforo (PRD 1.8 §5.6 e §5.6.1).

Puro, sem I/O. BRD 1.5: RN-EDG-01..07, RF-RNK-01, QA-14. Unidades em decimal: vol e pontos de vol
(0,01 = 1 ponto); edge relativo e spread normal adimensionais (razão sobre a RV prevista).

Notação: IV (prazo constante ex-evento), σ̂ com intervalo [σ̂_lo, σ̂_hi], *s* spread normal, *c*
custos por direção, *L* limiar.

- Prêmio p = IV − σ̂(1 + s); intervalo [IV − σ̂_hi(1 + s), IV − σ̂_lo(1 + s)].
- Edge relativo = p / σ̂ (= (IV − σ̂)/σ̂ − s).
- Semáforo (comparações estritas; empate nunca é edge líquido): venda se p_lo > c_v + L; compra se
  p_hi < −(c_c + L); sem edge se p_hi ≤ c_v + L e p_lo ≥ −(c_c + L); inconclusivo nos demais.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from vollab.quant.forecast import bootstrap_interval

NORMAL_SPREAD_SEED = 20261123


class EdgeState(StrEnum):
    EDGE = "edge"  # edge líquido
    INCONCLUSIVE = "inconclusive"
    NO_EDGE = "no_edge"
    UNAVAILABLE = "unavailable"  # fora do semáforo: falta insumo


class Direction(StrEnum):
    SELL = "sell"  # vender vol (IV cara)
    BUY = "buy"  # comprar vol (IV barata)


STATE_ORDER = {EdgeState.EDGE: 0, EdgeState.INCONCLUSIVE: 1, EdgeState.NO_EDGE: 2, EdgeState.UNAVAILABLE: 3}


# --- Spread normal (RN-EDG-07, QA-14) --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormalSpread:
    value: float
    ci_low: float | None
    ci_high: float | None
    n_pairs: int
    calibrated: bool


def normal_spread(
    implied: Sequence[float],
    realized: Sequence[float],
    *,
    min_pairs: int,
    default: float,
    reps: int,
    level: float,
) -> NormalSpread:
    """Mediana de (IVₖ − RVₖ)/RVₖ nas origens não sobrepostas. Abaixo de `min_pairs`, o padrão
    configurado, não calibrado (nunca zero implícito). Intervalo por bootstrap percentil."""
    iv = np.asarray(implied, dtype=np.float64)
    rv = np.asarray(realized, dtype=np.float64)
    ok = np.isfinite(iv) & np.isfinite(rv) & (rv > 0) & (iv > 0)
    x = (iv[ok] - rv[ok]) / rv[ok]
    n = int(x.size)
    if n < min_pairs:
        return NormalSpread(default, None, None, n, calibrated=False)
    ci = bootstrap_interval(
        lambda idx: np.median(x[idx], axis=1), n, reps=reps, level=level, seed=NORMAL_SPREAD_SEED
    )
    return NormalSpread(float(np.median(x)), ci.low, ci.high, n, calibrated=True)


# --- Prêmio, edge e semáforo ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Premium:
    value: float
    ci_low: float
    ci_high: float


def premium(iv: float, forecast: float, forecast_low: float, forecast_high: float, s: float) -> Premium:
    """RN-EDG-01: p = IV − σ̂(1 + s), intervalo herdado do de σ̂ (s pelo valor pontual)."""
    # O intervalo empírico (quantis do erro log) pode não conter σ̂ quando todos os erros têm o mesmo
    # sinal; só se exige que seja positivo e ordenado.
    if not (forecast > 0 and 0 < forecast_low <= forecast_high):
        raise ValueError("premium: previsão e intervalo positivos e ordenados.")
    k = 1.0 + s
    return Premium(iv - forecast * k, iv - forecast_high * k, iv - forecast_low * k)


@dataclass(frozen=True, slots=True)
class Signal:
    state: EdgeState
    direction: Direction
    required_sell: float  # c_v + L
    required_buy: float | None  # c_c + L (None: compra impossível pelo custo do hedge)
    net_relative: float | None  # edge relativo líquido na direção (None: compra inviável pelo hedge)
    net_premium: float | None  # |p| − c na direção (pontos), base do P&L esperado


def classify(
    p: Premium,
    *,
    forecast: float,
    cost_sell: float,
    cost_buy: float | None,
    threshold: float,
) -> Signal:
    """Semáforo nas duas direções (BRD 1.5 RN-EDG-03). `cost_buy` None: o hedge consome todo o edge
    de compra, que então nunca é líquido."""
    if forecast <= 0 or cost_sell < 0 or threshold < 0 or (cost_buy is not None and cost_buy < 0):
        raise ValueError("classify: previsão positiva; custos e limiar não negativos.")
    n_sell = cost_sell + threshold
    n_buy = None if cost_buy is None else cost_buy + threshold
    if p.ci_low > n_sell:
        state, direction = EdgeState.EDGE, Direction.SELL
    elif n_buy is not None and p.ci_high < -n_buy:
        state, direction = EdgeState.EDGE, Direction.BUY
    else:
        buy_floor = -n_buy if n_buy is not None else -math.inf
        inside = p.ci_high <= n_sell and p.ci_low >= buy_floor
        state = EdgeState.NO_EDGE if inside else EdgeState.INCONCLUSIVE
        direction = Direction.SELL if p.value >= 0 else Direction.BUY
    net: float | None
    if direction is Direction.SELL:
        net = p.value - cost_sell
    elif cost_buy is None:
        net = None
    else:
        net = -p.value - cost_buy
    return Signal(
        state=state,
        direction=direction,
        required_sell=n_sell,
        required_buy=n_buy,
        net_relative=None if net is None else net / forecast,
        net_premium=net,
    )


def ranking_key(state: EdgeState, net_relative: float | None, ticker: str) -> tuple[int, float, str]:
    """RF-RNK-01: estado, depois edge relativo líquido decrescente, depois o ticker."""
    nr = net_relative if net_relative is not None and math.isfinite(net_relative) else -math.inf
    return STATE_ORDER[state], -nr, ticker


# --- IV rank (RN-VOL-02, LC-03) ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IvRank:
    rank: float | None  # (IV − mín)/(máx − mín)
    percentile: float | None  # fração dos dias com IV ≤ a atual
    n_days: int


def iv_rank(history: Sequence[float], current: float, *, min_days: int) -> IvRank:
    h = np.asarray([v for v in history if v is not None and math.isfinite(v)], dtype=np.float64)
    n = int(h.size)
    if n < min_days:
        return IvRank(None, None, n)
    lo, hi = float(h.min()), float(h.max())
    rank = (current - lo) / (hi - lo) if hi > lo else 0.5
    return IvRank(min(max(rank, 0.0), 1.0), float(np.mean(h <= current)), n)
