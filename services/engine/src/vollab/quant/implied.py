"""IV por negócio, IV de referência diária, ATM, estrutura a termo, prazo constante e salto de evento.

Puro, sem I/O (PRD §4). Requisitos: RF-VOL-02..05, RN-VOL-03..06, RN-EVT-01..03, QA-03.
Fórmulas de evento conforme a referência técnica §3 Cap. 5 (eqs. 5.2–5.4).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.stats import chi2

# --- Sincronização temporal (RN-VOL-03) --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Para cada negócio de opção: índice do negócio do ativo usado (−1 = nenhum) e a defasagem."""

    underlying_index: NDArray[np.int64]
    lag_s: NDArray[np.float64]  # NaN quando não há negócio do ativo antes
    synced: NDArray[np.bool_]


def synchronize(option_time_s: ArrayLike, underlying_time_s: ArrayLike, *, max_lag_s: float) -> SyncResult:
    """Último negócio do ativo-objeto **até** o horário do negócio da opção (inclusive).

    `underlying_time_s` deve vir em ordem não decrescente. Pares com defasagem acima de
    `max_lag_s` são descartados (e contados por quem chama).
    """
    opt = np.asarray(option_time_s, dtype=np.float64)
    und = np.asarray(underlying_time_s, dtype=np.float64)
    if und.size and np.any(np.diff(und) < 0):
        raise ValueError("Negócios do ativo-objeto fora de ordem de horário.")
    idx = np.searchsorted(und, opt, side="right").astype(np.int64) - 1
    has = idx >= 0
    lag = np.full(opt.shape, np.nan)
    lag[has] = opt[has] - und[idx[has]]
    synced = has & (lag <= max_lag_s)
    return SyncResult(underlying_index=idx, lag_s=lag, synced=synced)


# --- IV de referência diária (RN-VOL-06) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReferenceIv:
    iv: float | None
    status: str  # ok | low_sample | no_iv
    trades_used: int


def reference_iv(time_s: ArrayLike, iv: ArrayLike, *, window_start_s: float, min_trades: int) -> ReferenceIv:
    """Mediana das IVs sincronizadas a partir de `window_start_s` (última hora), com no mínimo
    `min_trades`. Abaixo disso, a IV do último negócio sincronizado do dia, como baixa amostra."""
    t = np.asarray(time_s, dtype=np.float64)
    v = np.asarray(iv, dtype=np.float64)
    ok = np.isfinite(v)
    t, v = t[ok], v[ok]
    if v.size == 0:
        return ReferenceIv(None, "no_iv", 0)
    last_hour = t >= window_start_s
    if int(last_hour.sum()) >= min_trades:
        return ReferenceIv(float(np.median(v[last_hour])), "ok", int(last_hour.sum()))
    # Último no horário; em empate, o último na ordem recebida (quem chama ordena por horário e ID).
    last = len(t) - 1 - int(np.argmax(t[::-1]))
    return ReferenceIv(float(v[last]), "low_sample", 1)


# --- IV ATM por vencimento --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmilePoint:
    strike: float
    iv: float
    is_call: bool


@dataclass(frozen=True, slots=True)
class AtmResult:
    iv: float | None
    reason: str | None
    lower_strike: float | None = None
    upper_strike: float | None = None


def atm_iv(points: Sequence[SmilePoint], forward: float, *, k_min: float, k_max: float) -> AtmResult:
    """IV ATM: interpolação linear em ln(K/F) entre o strike imediatamente abaixo e o imediatamente
    acima do forward, usando a opção **fora do dinheiro** de cada strike (put abaixo, call acima),
    ou a outra quando só ela tem IV. Exige strikes dos dois lados dentro de K/F ∈ [k_min, k_max]
    (RN-VOL-05: "negócios ATM"); sem isso, indisponível, sem extrapolação."""
    return iv_at_moneyness(points, forward, 1.0, k_min=k_min, k_max=k_max)


def iv_at_moneyness(
    points: Sequence[SmilePoint], forward: float, target_kf: float, *, k_min: float, k_max: float
) -> AtmResult:
    """IV em K/F = `target_kf` (1 = ATM; PRD 1.8 usa 0,95 e 1,05 no skew): mesma regra da ATM —
    interpolação linear em ln(K/F) entre os strikes vizinhos do alvo, opção fora do dinheiro de cada
    strike (em relação ao forward), sem extrapolação."""
    if forward <= 0:
        return AtmResult(None, "forward inválido")
    by_strike: dict[float, dict[bool, float]] = {}
    for p in points:
        if math.isfinite(p.iv) and p.iv > 0 and k_min <= p.strike / forward <= k_max:
            by_strike.setdefault(p.strike, {})[p.is_call] = p.iv
    if not by_strike:
        return AtmResult(None, "sem IV de séries líquidas perto do dinheiro")

    def pick(k: float) -> float:
        ivs = by_strike[k]
        otm_is_call = k >= forward
        return ivs.get(otm_is_call, ivs.get(not otm_is_call, math.nan))

    target = forward * target_kf
    below = [k for k in by_strike if k <= target]
    above = [k for k in by_strike if k >= target]
    if not below or not above:
        side = "do dinheiro" if target_kf == 1.0 else f"de K/F = {target_kf:g}"
        return AtmResult(None, f"sem strikes líquidos dos dois lados {side}")
    k_lo, k_hi = max(below), min(above)
    if k_lo == k_hi:
        return AtmResult(pick(k_lo), None, k_lo, k_hi)
    x_lo, x_hi, x = math.log(k_lo / forward), math.log(k_hi / forward), math.log(target_kf)
    w = (x - x_lo) / (x_hi - x_lo)
    return AtmResult((1 - w) * pick(k_lo) + w * pick(k_hi), None, k_lo, k_hi)


# --- Prazo constante (RF-VOL-03, RN-VOL-05, QA-03) ----------------------------------------------


@dataclass(frozen=True, slots=True)
class TermPoint:
    t: float  # anos úteis até o vencimento
    iv: float  # IV ATM (decimal anualizado)
    total_variance_adj: float = 0.0  # variância de eventos a remover (ex-evento, RN-EVT-03)


@dataclass(frozen=True, slots=True)
class ConstantMaturity:
    iv: float | None
    reason: str | None
    t1: float | None = None
    t2: float | None = None


def constant_maturity(points: Sequence[TermPoint], target_t: float) -> ConstantMaturity:
    """Interpolação linear na **variância total** σ²·t entre os vencimentos que cercam o prazo-alvo.

    Sem dois vencimentos cercando o alvo, indisponível (sem extrapolação, RN-VOL-05). A variância
    de eventos (`total_variance_adj`) é subtraída de cada vencimento antes de interpolar.
    """
    pts = sorted((p for p in points if p.t > 0 and math.isfinite(p.iv)), key=lambda p: p.t)
    if len(pts) < 2:
        return ConstantMaturity(None, "sem dois vencimentos com IV ATM para interpolar")
    exact = [p for p in pts if math.isclose(p.t, target_t, rel_tol=0, abs_tol=1e-12)]
    if exact:
        p = exact[0]
        w_total = p.iv * p.iv * p.t - p.total_variance_adj
        if w_total <= 0:
            return ConstantMaturity(None, "variância ex-evento não positiva")
        return ConstantMaturity(math.sqrt(w_total / target_t), None, p.t, p.t)
    lower = [p for p in pts if p.t < target_t]
    upper = [p for p in pts if p.t > target_t]
    if not lower or not upper:
        return ConstantMaturity(None, "prazo-alvo fora dos vencimentos disponíveis (sem extrapolação)")
    p1, p2 = lower[-1], upper[0]
    w1 = p1.iv * p1.iv * p1.t - p1.total_variance_adj
    w2 = p2.iv * p2.iv * p2.t - p2.total_variance_adj
    if w1 <= 0 or w2 <= 0:
        return ConstantMaturity(None, "variância ex-evento não positiva")
    a = (p2.t - target_t) / (p2.t - p1.t)
    w = a * w1 + (1 - a) * w2
    if w <= 0:
        return ConstantMaturity(None, "variância interpolada não positiva")
    return ConstantMaturity(math.sqrt(w / target_t), None, p1.t, p2.t)


# --- Salto de evento (RN-EVT-01..03; referência §3 Cap. 5) -------------------------------------


def forward_vol(s1: float, t1: float, s2: float, t2: float) -> float | None:
    """Eq. 5.2: vol a termo entre t1 e t2 (None se a variância a termo não for positiva)."""
    w = (s2 * s2 * t2 - s1 * s1 * t1) / (t2 - t1)
    return math.sqrt(w) if w > 0 else None


def event_vol(s1: float, t1: float, s2: float, t2: float) -> float | None:
    """Eq. 5.3: σ_E = sqrt((σ₁² − σ₂²)·t1·t2/(t2 − t1)). None se σ₁ ≤ σ₂ (sem salto precificado).

    σ_E é o desvio-padrão do retorno no dia do evento (decimal, **não anualizado**).
    """
    if s1 <= s2 or t2 <= t1:
        return None
    return math.sqrt((s1 * s1 - s2 * s2) * t1 * t2 / (t2 - t1))


def event_expected_move(s1: float, t1: float, s2: float, t2: float) -> float | None:
    """Eq. 5.4: E|R| = sqrt(2/π)·σ_E."""
    se = event_vol(s1, t1, s2, t2)
    return None if se is None else math.sqrt(2.0 / math.pi) * se


@dataclass(frozen=True, slots=True)
class HistoricalJump:
    value: float | None  # σ_E histórico (decimal, não anualizado)
    ci_low: float | None
    ci_high: float | None
    n: int


def historical_jump(
    event_returns: ArrayLike, normal_daily_variance: float, *, ci_level: float
) -> HistoricalJump:
    """σ_E pelos retornos (log, ajustados) em datas de resultado passadas, com média zero:
    σ_E² = média(r²) − variância diária normal (piso zero). Intervalo pela distribuição
    qui-quadrado de n·média(r²)/E[r²] (retornos normais), com a mesma subtração; com poucos
    eventos ele sai naturalmente largo (RN-EVT-02)."""
    r = np.asarray(event_returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    n = int(r.size)
    if n == 0:
        return HistoricalJump(None, None, None, 0)
    m2 = float(np.mean(r * r))
    alpha = 1.0 - ci_level
    lo_m2 = n * m2 / float(chi2.ppf(1 - alpha / 2, n))
    hi_m2 = n * m2 / float(chi2.ppf(alpha / 2, n))

    def jump(x: float) -> float:
        return math.sqrt(max(x - normal_daily_variance, 0.0))

    return HistoricalJump(jump(m2), jump(lo_m2), jump(hi_m2), n)
