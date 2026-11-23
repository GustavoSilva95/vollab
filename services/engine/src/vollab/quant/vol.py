"""Estimadores de volatilidade realizada (RF-VOL-01, RN-VOL-01/07/08/09; PRD §5.5).

Puro, sem I/O. Fórmulas conforme a referência técnica (`docs/referencia/volatility-trading.md`,
§3 Cap. 2 e Errata §2), **sempre na forma corrigida**:
- Garman-Klass com ln(C/O) (o livro imprime ln(Cₜ/Cₜ₋₁));
- Rogers-Satchell com O = **abertura**;
- Yang-Zhang com σ²ₒ = var de ln(Oₜ/Cₜ₋₁) e σ²ᶜ = var de ln(Cₜ/Oₜ);
- close-to-close padrão com **média zero e divisor n** (eq. 2.1b).

Convenções: variância diária média na janela × 252 (RN-VOL-01); a vol é a raiz. O fechamento
anterior já chega **ajustado por proventos** (RN-VOL-07). Valores ausentes são NaN: uma janela
com qualquer pregão ausente ou inválido não gera número (PRD §5.5, PR-03).
"""

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import ArrayLike, NDArray
from scipy.special import gammaln

ANNUALIZATION = 252
_LN2 = math.log(2.0)

FloatArray = NDArray[np.float64]


class Estimator(StrEnum):
    """Nomes gravados em `realized_vols.estimator` (PRD §6.2)."""

    CLOSE_TO_CLOSE = "close_to_close"
    CLOSE_TO_CLOSE_DEMEANED = "close_to_close_demeaned"
    PARKINSON = "parkinson"
    GARMAN_KLASS = "garman_klass"
    ROGERS_SATCHELL = "rogers_satchell"
    YANG_ZHANG = "yang_zhang"
    INTRADAY_5M = "intraday_5m"


# --- Correção de viés da vol (desigualdade de Jensen; referência §3 Cap. 2) ------------------


def bias_b(n: int) -> float:
    """b(N) da eq. 2.6: E[s] = b(N)·σ para s com divisor N e **média subtraída** (eq. 2.1a).

    Nunca use com o estimador de média zero: para ele o fator é `bias_b_zero_mean`.
    """
    if n < 2:
        raise ValueError("bias_b exige N ≥ 2.")
    return math.sqrt(2.0 / n) * math.exp(gammaln(n / 2) - gammaln((n - 1) / 2))


def bias_b_zero_mean(n: int) -> float:
    """b₀(N): E[s] = b₀(N)·σ para s = sqrt(Σx²/N) com **média zero** (eq. 2.1b)."""
    if n < 1:
        raise ValueError("bias_b_zero_mean exige N ≥ 1.")
    return math.sqrt(2.0 / n) * math.exp(gammaln((n + 1) / 2) - gammaln(n / 2))


def bias_c4(n: int) -> float:
    """c₄(N) = b(N)·sqrt(N/(N − 1)): fator da vol com média subtraída e divisor N − 1 (eq. 2.3)."""
    return bias_b(n) * math.sqrt(n / (n - 1))


# --- Termos diários ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DailyTerms:
    """Termos por pregão, alinhados ao calendário (NaN = pregão ausente ou inválido).

    - `ret_cc`: ln(Cₜ / Cₜ₋₁ ajustado)
    - `ret_on`: ln(Oₜ / Cₜ₋₁ ajustado)  (noite)
    - `ret_oc`: ln(Cₜ / Oₜ)              (pregão)
    - `hl2`:    ln(Hₜ / Lₜ)²
    - `rs`:     ln(H/C)·ln(H/O) + ln(L/C)·ln(L/O)
    """

    ret_cc: FloatArray
    ret_on: FloatArray
    ret_oc: FloatArray
    hl2: FloatArray
    rs: FloatArray


def valid_ohlc(o: FloatArray, h: FloatArray, low: FloatArray, c: FloatArray) -> NDArray[np.bool_]:
    """OHLC coerente: preços positivos, máxima ≥ abertura/fechamento/mínima, mínima ≤ abertura/fechamento."""
    with np.errstate(invalid="ignore"):
        return (
            np.isfinite(o)
            & np.isfinite(h)
            & np.isfinite(low)
            & np.isfinite(c)
            & (low > 0)
            & (h >= np.maximum(o, c))
            & (low <= np.minimum(o, c))
        )


def daily_terms(
    o: ArrayLike, h: ArrayLike, low: ArrayLike, c: ArrayLike, prev_close_adj: ArrayLike
) -> DailyTerms:
    """Termos diários a partir do OHLC oficial e do fechamento anterior já ajustado (RN-VOL-07)."""
    oa, ha, la, ca = (np.asarray(x, dtype=np.float64) for x in (o, h, low, c))
    pc = np.asarray(prev_close_adj, dtype=np.float64)
    ok = valid_ohlc(oa, ha, la, ca)
    with np.errstate(invalid="ignore", divide="ignore"):
        prev_ok = ok & np.isfinite(pc) & (pc > 0)
        nan = np.full(oa.shape, np.nan)
        ret_cc = np.where(prev_ok, np.log(ca / pc), nan)
        ret_on = np.where(prev_ok, np.log(oa / pc), nan)
        ret_oc = np.where(ok, np.log(ca / oa), nan)
        hl2 = np.where(ok, np.log(ha / la) ** 2, nan)
        rs = np.where(
            ok,
            np.log(ha / ca) * np.log(ha / oa) + np.log(la / ca) * np.log(la / oa),
            nan,
        )
    return DailyTerms(ret_cc=ret_cc, ret_on=ret_on, ret_oc=ret_oc, hl2=hl2, rs=rs)


# --- Variância diária de uma janela (arrays de tamanho n, sem NaN) -----------------------------


def var_close_to_close(ret: FloatArray) -> float:
    """Média zero, divisor n (eq. 2.1b). Sem n/(n − 1): a média zero não perde grau de liberdade."""
    return float(np.mean(ret * ret))


def var_close_to_close_demeaned(ret: FloatArray) -> float:
    """Média subtraída, divisor n − 1 (eq. 2.3)."""
    return float(np.var(ret, ddof=1))


def var_parkinson(hl2: FloatArray) -> float:
    return float(np.mean(hl2) / (4.0 * _LN2))


def var_garman_klass(hl2: FloatArray, ret_oc: FloatArray) -> float:
    """Forma original (1980): ½ ln(H/L)² − (2 ln 2 − 1) ln(C/O)². Errata: ln(C/O), não ln(Cₜ/Cₜ₋₁)."""
    return float(np.mean(0.5 * hl2 - (2.0 * _LN2 - 1.0) * ret_oc * ret_oc))


def var_rogers_satchell(rs: FloatArray) -> float:
    return float(np.mean(rs))


def yang_zhang_k(n: int) -> float:
    return 0.34 / (1.34 + (n + 1) / (n - 1))


def var_yang_zhang(ret_on: FloatArray, ret_oc: FloatArray, rs: FloatArray) -> float:
    """σ²ₒ + k·σ²ᶜ + (1 − k)·σ²_RS; σ²ₒ e σ²ᶜ com média subtraída e n − 1 (eq. 2.17, Errata)."""
    n = len(ret_on)
    k = yang_zhang_k(n)
    return float(np.var(ret_on, ddof=1) + k * np.var(ret_oc, ddof=1) + (1.0 - k) * np.mean(rs))


def var_intraday(intraday_var: FloatArray, ret_on: FloatArray) -> float:
    """RN-VOL-08: soma dos quadrados dos retornos de 5 min (já somada por pregão) + noite²."""
    return float(np.mean(intraday_var + ret_on * ret_on))


# --- Janelas móveis ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RollingResult:
    """Uma entrada por pregão do calendário: variância anualizada (não corrigida) e vol exibida.

    `variance_annual` é a que alimenta previsão e GARCH (PRD §5.5); `vol` é a vol exibida,
    corrigida pelo viés de Jensen onde existe fator definido (close-to-close nas duas formas).
    NaN = janela sem dados suficientes; `missing` = nº de pregões ausentes ou inválidos na janela.
    """

    variance_annual: FloatArray
    vol: FloatArray
    missing: NDArray[np.int64]


def _windows(x: FloatArray, n: int) -> FloatArray:
    padded = np.concatenate([np.full(n - 1, np.nan), x])
    return sliding_window_view(padded, n)


def rolling(
    estimator: Estimator,
    terms: DailyTerms,
    n: int,
    *,
    intraday_var: FloatArray | None = None,
) -> RollingResult:
    """RV em janelas de `n` pregões terminando em cada pregão do calendário."""
    if n < 2:
        raise ValueError("A janela precisa de ao menos 2 pregões.")
    match estimator:
        case Estimator.CLOSE_TO_CLOSE:
            inputs = [terms.ret_cc]
        case Estimator.CLOSE_TO_CLOSE_DEMEANED:
            inputs = [terms.ret_cc]
        case Estimator.PARKINSON:
            inputs = [terms.hl2]
        case Estimator.GARMAN_KLASS:
            inputs = [terms.hl2, terms.ret_oc]
        case Estimator.ROGERS_SATCHELL:
            inputs = [terms.rs]
        case Estimator.YANG_ZHANG:
            inputs = [terms.ret_on, terms.ret_oc, terms.rs]
        case Estimator.INTRADAY_5M:
            if intraday_var is None:
                raise ValueError("O estimador intradiário exige a variância intradiária por pregão.")
            inputs = [intraday_var, terms.ret_on]
    wins = [_windows(np.asarray(x, dtype=np.float64), n) for x in inputs]
    bad = np.zeros(wins[0].shape[0], dtype=np.int64)
    day_bad = np.zeros(wins[0].shape, dtype=bool)
    for w in wins:
        day_bad |= ~np.isfinite(w)
    bad = day_bad.sum(axis=1).astype(np.int64)
    ok = bad == 0
    var_daily = np.full(bad.shape, np.nan)
    if ok.any():
        sel = [w[ok] for w in wins]
        match estimator:
            case Estimator.CLOSE_TO_CLOSE:
                v = np.mean(sel[0] ** 2, axis=1)
            case Estimator.CLOSE_TO_CLOSE_DEMEANED:
                v = np.var(sel[0], axis=1, ddof=1)
            case Estimator.PARKINSON:
                v = np.mean(sel[0], axis=1) / (4.0 * _LN2)
            case Estimator.GARMAN_KLASS:
                v = np.mean(0.5 * sel[0] - (2.0 * _LN2 - 1.0) * sel[1] ** 2, axis=1)
            case Estimator.ROGERS_SATCHELL:
                v = np.mean(sel[0], axis=1)
            case Estimator.YANG_ZHANG:
                k = yang_zhang_k(n)
                v = (
                    np.var(sel[0], axis=1, ddof=1)
                    + k * np.var(sel[1], axis=1, ddof=1)
                    + (1.0 - k) * np.mean(sel[2], axis=1)
                )
            case Estimator.INTRADAY_5M:
                v = np.mean(sel[0] + sel[1] ** 2, axis=1)
        var_daily[ok] = v
    variance_annual = var_daily * ANNUALIZATION
    with np.errstate(invalid="ignore"):
        positive = variance_annual > 0
        raw_vol = np.where(positive, np.sqrt(np.where(positive, variance_annual, 1.0)), np.nan)
    factor = display_factor(estimator, n)
    return RollingResult(
        variance_annual=np.where(positive, variance_annual, np.nan),
        vol=raw_vol / factor,
        missing=bad,
    )


def display_factor(estimator: Estimator, n: int) -> float:
    """Divisor da vol exibida (PRD §5.5): b₀(n) no close-to-close de média zero, c₄(n) no com média
    subtraída. Os demais estimadores não têm fator fechado na referência e são exibidos sem correção."""
    match estimator:
        case Estimator.CLOSE_TO_CLOSE:
            return bias_b_zero_mean(n)
        case Estimator.CLOSE_TO_CLOSE_DEMEANED:
            return bias_c4(n)
        case _:
            return 1.0
