"""T-REF-05 (PRD §10.2): estimadores de vol realizada contra cálculo independente.

1. Implementação ingênua em laço sobre 221 pregões reais (COTAHIST anual, recorte das fixtures),
   em todas as janelas de 20 e 60 pregões: erro < 1e-10.
2. "Planilha de referência": 7 pregões de PETR4 (02/01 a 12/01/2026) com valores calculados à parte
   em mpmath com 40 dígitos (script no docstring de `PLANILHA`): erro < 1e-10.
3. Casos da §7 da referência técnica: `bias_b` e `bias_b_zero_mean`.
4. Propriedade em série sintética (MBG sem drift e sem gap, σ = 30%): todos convergem para σ dentro
   da tolerância documentada em `SYNTHETIC_TOLERANCE`.
"""

import math
from pathlib import Path

import numpy as np
import pytest

from tests.conftest import FIXTURES
from vollab.data.b3_cotahist import RecordFilter, read_cotahist
from vollab.quant.intraday import build_session, realized_variance_naive
from vollab.quant.vol import (
    Estimator,
    bias_b,
    bias_b_zero_mean,
    bias_c4,
    daily_terms,
    rolling,
)

pytestmark = pytest.mark.reference

DAILY_ESTIMATORS = [e for e in Estimator if e is not Estimator.INTRADAY_5M]
NEED_PREVIOUS_CLOSE = {Estimator.CLOSE_TO_CLOSE, Estimator.CLOSE_TO_CLOSE_DEMEANED, Estimator.YANG_ZHANG}


def _ohlc(ticker: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    content = Path(FIXTURES / "b3/cotahist/COTAHIST_A2026_recorte.ZIP").read_bytes()
    parsed = read_cotahist(
        content,
        keep=RecordFilter(underlying_tickers=[ticker], underlying_isins=[], options=False),
        annual=True,
    )
    recs = sorted((r for r in parsed.records if r.ticker == ticker), key=lambda r: r.trade_date)
    arr = np.array([[float(r.open), float(r.high), float(r.low), float(r.last)] for r in recs])
    return arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]


# --- Implementação ingênua (laços, sem numpy) ----------------------------------------------------


def _naive_var(
    estimator: Estimator, o: list[float], h: list[float], lo: list[float], c: list[float]
) -> float:
    """Janela com len(o) − 1 pregões: o índice 0 só fornece o fechamento anterior."""
    n = len(o) - 1
    cc = [math.log(c[i] / c[i - 1]) for i in range(1, n + 1)]
    on = [math.log(o[i] / c[i - 1]) for i in range(1, n + 1)]
    oc = [math.log(c[i] / o[i]) for i in range(1, n + 1)]
    hl = [math.log(h[i] / lo[i]) for i in range(1, n + 1)]
    rs = [
        math.log(h[i] / c[i]) * math.log(h[i] / o[i]) + math.log(lo[i] / c[i]) * math.log(lo[i] / o[i])
        for i in range(1, n + 1)
    ]

    def var1(x: list[float]) -> float:
        m = sum(x) / len(x)
        return sum((a - m) ** 2 for a in x) / (len(x) - 1)

    match estimator:
        case Estimator.CLOSE_TO_CLOSE:
            return sum(a * a for a in cc) / n
        case Estimator.CLOSE_TO_CLOSE_DEMEANED:
            return var1(cc)
        case Estimator.PARKINSON:
            return sum(a * a for a in hl) / n / (4 * math.log(2))
        case Estimator.GARMAN_KLASS:
            return sum(0.5 * a * a - (2 * math.log(2) - 1) * b * b for a, b in zip(hl, oc, strict=True)) / n
        case Estimator.ROGERS_SATCHELL:
            return sum(rs) / n
        case Estimator.YANG_ZHANG:
            k = 0.34 / (1.34 + (n + 1) / (n - 1))
            return var1(on) + k * var1(oc) + (1 - k) * sum(rs) / n
    raise AssertionError(estimator)


@pytest.mark.parametrize("ticker", ["PETR4", "BOVA11"])
@pytest.mark.parametrize("window", [20, 60])
@pytest.mark.parametrize("estimator", DAILY_ESTIMATORS)
def test_tref05_rolling_matches_naive_loop(ticker: str, window: int, estimator: Estimator) -> None:
    o, h, lo, c = _ohlc(ticker)
    prev = np.concatenate([[np.nan], c[:-1]])
    res = rolling(estimator, daily_terms(o, h, lo, c, prev), window)
    checked = 0
    for end in range(len(c)):
        start = end - window  # precisa de window + 1 fechamentos
        if start < 0:
            # Sem o fechamento anterior só os estimadores de range (sem noite) têm valor.
            if estimator in NEED_PREVIOUS_CLOSE or start < -1:
                assert math.isnan(res.variance_annual[end])
            continue
        expected = _naive_var(
            estimator,
            list(o[start : end + 1]),
            list(h[start : end + 1]),
            list(lo[start : end + 1]),
            list(c[start : end + 1]),
        )
        assert abs(res.variance_annual[end] - expected * 252) < 1e-10
        checked += 1
    assert checked == len(c) - window


# --- Planilha de referência -------------------------------------------------------------------

# PETR4, COTAHIST oficial (abertura, máxima, mínima, fechamento). Valores esperados: vol anualizada
# sem correção de viés, sqrt(variância × 252), calculados em mpmath (mp.dps = 40) com as fórmulas da
# referência técnica na forma corrigida.
PLANILHA = [
    (30.96, 30.96, 30.36, 30.71),
    (30.70, 30.77, 29.73, 30.20),
    (30.37, 30.43, 29.62, 29.64),
    (29.67, 29.83, 29.53, 29.83),
    (29.91, 30.34, 29.79, 30.20),
    (30.17, 30.74, 30.14, 30.30),
    (30.30, 30.57, 30.21, 30.36),
]
PLANILHA_ESPERADO = {
    Estimator.CLOSE_TO_CLOSE: 0.18765153738647093,
    Estimator.CLOSE_TO_CLOSE_DEMEANED: 0.20285974293889568,
    Estimator.PARKINSON: 0.20871963934874859,
    Estimator.GARMAN_KLASS: 0.20992851765032766,
    Estimator.ROGERS_SATCHELL: 0.21830983921646294,
    Estimator.YANG_ZHANG: 0.22172917720372699,
}


@pytest.mark.parametrize("estimator", DAILY_ESTIMATORS)
def test_tref05_reference_spreadsheet(estimator: Estimator) -> None:
    arr = np.array(PLANILHA)
    o, h, lo, c = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    prev = np.concatenate([[np.nan], c[:-1]])
    res = rolling(estimator, daily_terms(o, h, lo, c, prev), 6)
    raw_vol = math.sqrt(res.variance_annual[-1])
    assert abs(raw_vol - PLANILHA_ESPERADO[estimator]) < 1e-10
    # Vol exibida: só o close-to-close leva correção de viés, com o fator da sua forma.
    if estimator is Estimator.CLOSE_TO_CLOSE:
        assert res.vol[-1] == pytest.approx(raw_vol / bias_b_zero_mean(6), abs=1e-14)
    elif estimator is Estimator.CLOSE_TO_CLOSE_DEMEANED:
        assert res.vol[-1] == pytest.approx(raw_vol / bias_c4(6), abs=1e-14)
    else:
        assert res.vol[-1] == raw_vol


# --- Casos da §7 da referência técnica ----------------------------------------------------------


def test_tref05_bias_factors_reference_cases() -> None:
    assert bias_b(5) == pytest.approx(0.840749, abs=1e-5)
    assert bias_b(100) == pytest.approx(0.992478, abs=1e-5)
    assert bias_b_zero_mean(5) == pytest.approx(0.951533, abs=1e-5)
    assert bias_b_zero_mean(20) == pytest.approx(0.987583, abs=1e-5)
    assert bias_b_zero_mean(100) == pytest.approx(0.997503, abs=1e-5)
    # c4 clássico: sqrt(2/(n−1))·Γ(n/2)/Γ((n−1)/2).
    n = 20
    c4 = math.sqrt(2 / (n - 1)) * math.exp(math.lgamma(n / 2) - math.lgamma((n - 1) / 2))
    assert bias_c4(n) == pytest.approx(c4, rel=1e-14)


def test_tref05_bias_factors_by_simulation() -> None:
    """Fatores conferidos por simulação (STATUS, 2026-11-22: N = 20, 0,98741 × 0,98758)."""
    rng = np.random.default_rng(20261122)
    x = rng.standard_normal((200_000, 20))
    s0 = np.sqrt(np.mean(x * x, axis=1))
    s1 = np.std(x, axis=1, ddof=1)
    assert s0.mean() == pytest.approx(bias_b_zero_mean(20), abs=1e-3)
    assert s1.mean() == pytest.approx(bias_c4(20), abs=1e-3)


def test_tref05_missing_day_makes_window_insufficient() -> None:
    o, h, lo, c = _ohlc("PETR4")
    o = o.copy()
    o[100] = np.nan
    prev = np.concatenate([[np.nan], c[:-1]])
    res = rolling(Estimator.YANG_ZHANG, daily_terms(o, h, lo, c, prev), 20)
    assert np.isnan(res.vol[100:120]).all()
    assert (res.missing[100:120] == 1).all()
    assert np.isfinite(res.vol[120])


# --- Propriedade: MBG sintético ----------------------------------------------------------------

# Tolerâncias documentadas (σ = 30%, 2.000 pregões, 780 passos por pregão, sem drift e sem gap):
# - close-to-close: erro de amostragem σ/sqrt(2N) ≈ 0,47 ponto → tolerância de 4 erros-padrão (6%);
# - range (Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang): viés para baixo da amostragem
#   discreta da máxima e da mínima (≈ 2–3% com 780 passos; referência §3 Cap. 2) → 6%;
# - intradiária (5 min = 156 barras de 5 passos): converge mais rápido → 3%.
SYNTHETIC_TOLERANCE = {
    Estimator.CLOSE_TO_CLOSE: 0.06,
    Estimator.CLOSE_TO_CLOSE_DEMEANED: 0.06,
    Estimator.PARKINSON: 0.06,
    Estimator.GARMAN_KLASS: 0.06,
    Estimator.ROGERS_SATCHELL: 0.06,
    Estimator.YANG_ZHANG: 0.06,
    Estimator.INTRADAY_5M: 0.03,
}


def test_tref05_synthetic_gbm_convergence() -> None:
    sigma, days, steps = 0.30, 2000, 780
    rng = np.random.default_rng(42)
    dt = 1.0 / (252 * steps)
    incr = sigma * math.sqrt(dt) * rng.standard_normal((days, steps)) - 0.5 * sigma**2 * dt
    log_path = np.cumsum(incr.ravel()).reshape(days, steps)
    start = np.concatenate([[0.0], log_path[:-1, -1]])  # sem gap: abre no fechamento anterior
    full = np.concatenate([start[:, None], log_path], axis=1)
    prices = 30.0 * np.exp(full)
    o, c = prices[:, 0], prices[:, -1]
    h, lo = prices.max(axis=1), prices.min(axis=1)
    prev = np.concatenate([[np.nan], c[:-1]])
    terms = daily_terms(o, h, lo, c, prev)
    # Variância intradiária: barras de 5 min = 5 passos de ~30 s (156 barras por pregão).
    bars = prices[:, ::5]
    path = np.concatenate([bars, c[:, None]], axis=1)
    intraday_var = np.sum(np.diff(np.log(path), axis=1) ** 2, axis=1)
    window = days - 1
    for est, tol in SYNTHETIC_TOLERANCE.items():
        res = rolling(est, terms, window, intraday_var=intraday_var)
        got = math.sqrt(res.variance_annual[-1])
        assert got == pytest.approx(sigma, rel=tol), est


# --- Intradiária (RN-VOL-08) ---------------------------------------------------------------------


def test_tref05_intraday_session_against_naive() -> None:
    # 10:00–18:00, barras de 5 min; negócios em horários escolhidos à mão.
    t = [36000 + 10, 36000 + 200, 36000 + 310, 36000 + 3600 * 3, 64800 + 330]  # o último é o leilão
    ids = [1, 2, 3, 4, 5]
    p = [30.0, 30.2, 30.1, 30.5, 30.6]
    q = [100] * 5
    s = build_session(t, ids, p, q, official_open=30.0, official_close=30.6, min_coverage=0.8)
    assert s.session_close_s == 64800  # 18:05:30 → 18:00
    assert s.bars_total == 96
    assert s.bars_with_trades == 3
    assert not s.complete
    # Caminho: abertura → barras (vazias repetem) → fechamento oficial.
    path = [30.0, 30.2, 30.1] + [30.1] * (36 - 2) + [30.5] * (96 - 36) + [30.6]
    assert s.intraday_variance == pytest.approx(realized_variance_naive(path), abs=1e-15)


def test_intraday_order_by_trade_id_not_time() -> None:
    # Negócio reemitido leva o horário da correção; dentro da barra vale o maior identificador.
    t = [36000 + 10, 36000 + 20, 64800 + 300]
    ids = [2, 1, 3]
    p = [30.4, 30.1, 30.5]
    s = build_session(t, ids, p, [1, 1, 1], official_open=30.0, official_close=30.5)
    assert s.bar_price[0] == 30.4
