"""Cenário de crise histórica (PRD 1.10 §5.9; BRD 1.7 QA-12).

Puro, sem I/O. Para um ativo e um episódio:
- choque de preço = pior retorno log acumulado em `horizon` pregões consecutivos dentro do episódio,
  com retornos ajustados por proventos (RN-VOL-07), gravado como retorno simples (e^r − 1);
- choque de vol = IV ATM no último pregão da janela − IV ATM no pregão anterior ao início (pontos de
  vol em decimal). IV ATM aproximada pelos **fechamentos** (não sincronizados) das opções; sem ela,
  RV close-to-close de média zero em 20 pregões no fim − no início (também aproximada).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from vollab.quant.pricing import BUSINESS_DAYS_PER_YEAR, IvStatus, implied_vol

RV_WINDOW = 20


@dataclass(frozen=True, slots=True)
class Window:
    start: int  # índice do primeiro retorno da janela (o pregão anterior é start − 1)
    end: int  # índice do último retorno (inclusive)
    log_return: float

    @property
    def simple_return(self) -> float:
        return math.expm1(self.log_return)


def worst_window(log_returns: Sequence[float], lo: int, hi: int, horizon: int) -> Window | None:
    """Pior soma de `horizon` retornos consecutivos com índices em [lo, hi] (inclusive). Janela com
    retorno ausente (NaN) não conta. None se o episódio for menor que o horizonte."""
    r = np.asarray(log_returns, dtype=np.float64)
    best: Window | None = None
    for s in range(max(lo, 0), hi - horizon + 2):
        e = s + horizon - 1
        if e > hi or e >= r.size:
            break
        chunk = r[s : e + 1]
        if not np.all(np.isfinite(chunk)):
            continue
        total = float(chunk.sum())
        if best is None or total < best.log_return:
            best = Window(s, e, total)
    return best


def worst_day(log_returns: Sequence[float], lo: int, hi: int) -> tuple[int, float] | None:
    r = np.asarray(log_returns, dtype=np.float64)
    idx = [i for i in range(max(lo, 0), min(hi, r.size - 1) + 1) if math.isfinite(r[i])]
    if not idx:
        return None
    i = min(idx, key=lambda j: r[j])
    return i, float(r[i])


def rv_zero_mean(log_returns: Sequence[float], end: int, window: int = RV_WINDOW) -> float | None:
    """RV close-to-close de média zero (eq. 2.1b) nos `window` retornos que terminam em `end`."""
    if end - window + 1 < 0:
        return None
    r = np.asarray(log_returns[end - window + 1 : end + 1], dtype=np.float64)
    if r.size < window or not np.all(np.isfinite(r)):
        return None
    return math.sqrt(BUSINESS_DAYS_PER_YEAR * float(np.mean(r * r)))


@dataclass(frozen=True, slots=True)
class OptionClose:
    """Fechamento de uma opção num pregão (COTAHIST)."""

    is_call: bool
    strike: float
    days_to_expiry_bd: int
    close: float
    trades_count: int


def atm_iv(
    spot: float,
    options: Sequence[OptionClose],
    rate_c: float,
    *,
    min_days_bd: int = 10,
    min_trades: int = 20,
) -> float | None:
    """IV ATM aproximada: média das IVs da call e da put com o strike mais próximo de S, no primeiro
    vencimento com ≥ `min_days_bd`, as duas com ≥ `min_trades` negócios. None sem par válido."""
    eligible = [o for o in options if o.days_to_expiry_bd >= min_days_bd and o.trades_count >= min_trades]
    if not eligible:
        return None
    for days in sorted({o.days_to_expiry_bd for o in eligible}):
        same = [o for o in eligible if o.days_to_expiry_bd == days]
        calls = {o.strike: o for o in same if o.is_call}
        puts = {o.strike: o for o in same if not o.is_call}
        strikes = sorted(set(calls) & set(puts), key=lambda k: (abs(k - spot), k))
        if not strikes:
            continue
        k = strikes[0]
        c, p = calls[k], puts[k]
        t = days / BUSINESS_DAYS_PER_YEAR
        res = implied_vol(np.array([c.close, p.close]), spot, k, t, rate_c, np.array([True, False]), 0.0)
        if not np.all(res.status == IvStatus.OK):
            return None
        return float(np.mean(res.iv))
    return None


@dataclass(frozen=True, slots=True)
class CrisisShock:
    status: str  # ok | unavailable
    reason: str | None
    window_start: date | None
    window_end: date | None
    price_shock: float | None  # retorno simples
    worst_day: date | None
    worst_day_return: float | None
    vol_shock: float | None  # pontos de vol (decimal)
    vol_method: str | None  # atm_iv | rv20
    vol_before: float | None
    vol_after: float | None
