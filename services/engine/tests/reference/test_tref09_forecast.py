"""T-REF-09 (PRD 1.7 §10.2): previsão de RV e avaliação de modelos.

1. Janelas não sobrepostas (propriedade, hypothesis): nenhum pregão em duas janelas realizadas,
   espaçamento de h pregões, ancoragem no fim e máximo de janelas possível.
2. Sem olhar à frente: perturbar retornos depois da origem não muda a previsão (EWMA, combinação,
   GARCH).
3. EWMA contra laço ingênuo (eq. 4.1).
4. GARCH: previsão contra a eq. 4.9 da referência (`garch_forecast`, §6) e vol de longo prazo do caso
   MSFT da §7 (≈ 0,142); recuperação dos parâmetros em série sintética.
5. Métricas de erro e razão de RMSE contra cálculo manual; bootstrap determinístico.
6. Intervalo χ² da previsão: cobertura ≈ nível em simulação; χ² da vol amostral idem.
"""

import itertools
import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vollab.quant.forecast import (
    ANNUALIZATION,
    GarchFailure,
    GarchFit,
    chi2_forecast_interval,
    chi2_vol_interval,
    combination_variance,
    empirical_forecast_interval,
    error_metrics,
    ewma_path,
    fit_garch,
    garch_term_variance,
    log_error_quantiles,
    non_overlapping_origins,
    realized_vol,
    rmse_interval,
    rmse_ratio,
)

pytestmark = pytest.mark.reference


# --- 1. Janelas não sobrepostas -------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(n_days=st.integers(1, 2000), horizon=st.integers(1, 260), first=st.integers(0, 300))
def test_windows_do_not_share_any_day(n_days: int, horizon: int, first: int) -> None:
    origins = non_overlapping_origins(n_days, horizon, first=first)
    seen: set[int] = set()
    for t in origins:
        window = set(range(t + 1, t + horizon + 1))
        assert not (window & seen), "um pregão em duas janelas"
        seen |= window
        assert t >= first
        assert t + horizon <= n_days - 1, "janela além do último pregão"
    if origins:
        assert origins[-1] + horizon == n_days - 1, "ancoragem no fim"
        assert all(b - a == horizon for a, b in itertools.pairwise(origins))
        # Máximo: não cabe mais uma janela antes da primeira.
        assert origins[0] - horizon < first
    else:
        assert n_days - 1 - horizon < first


def test_windows_known_case() -> None:
    # 221 pregões, h = 21: última origem 199 (janela 200..220), depois 178, 157, …
    origins = non_overlapping_origins(221, 21)
    assert origins[-1] == 199
    assert origins[:2] == [10, 31]
    assert len(origins) == 10


# --- 2. Sem olhar à frente --------------------------------------------------------------------


def _returns(n: int, sigma_daily: float, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n) * sigma_daily


@settings(max_examples=60, deadline=None)
@given(t=st.integers(60, 280), seed=st.integers(0, 10_000))
def test_ewma_and_combination_ignore_the_future(t: int, seed: int) -> None:
    r = _returns(300, 0.02, seed)
    r_future = r.copy()
    r_future[t + 1 :] *= 7.0
    a = ewma_path(r, 0.94)
    b = ewma_path(r_future, 0.94)
    np.testing.assert_array_equal(a.next_var[: t + 1], b.next_var[: t + 1])
    # A combinação é uma média de estimadores que já são janelas que terminam em t.
    va, _ = combination_variance([r**2, r**2 * 1.1, r**2 * 0.9])
    vb, _ = combination_variance([r_future**2, r_future**2 * 1.1, r_future**2 * 0.9])
    np.testing.assert_array_equal(va[: t + 1], vb[: t + 1])


def test_garch_ignores_the_future() -> None:
    r = _simulate_garch(600, 2e-6, 0.08, 0.90, seed=3)
    t = 400
    shocked = r.copy()
    shocked[t + 1 :] *= 5.0
    a = fit_garch(r[: t + 1], min_returns=240)
    b = fit_garch(shocked[: t + 1], min_returns=240)
    assert isinstance(a, GarchFit) and a == b


# --- 3. EWMA ----------------------------------------------------------------------------------


def test_ewma_matches_naive_loop() -> None:
    r = _returns(250, 0.018, 7)
    r[[30, 31, 100]] = np.nan  # pregões sem retorno válido repetem a variância
    lam = 0.94
    path = ewma_path(r, lam, init_n=20)
    valid = [x for x in r if math.isfinite(x)]
    v = sum(x * x for x in valid[:20]) / 20
    expected_after = {20: v}
    for k, x in enumerate(valid[20:], start=21):
        v = lam * v + (1 - lam) * x * x
        expected_after[k] = v
    for i in range(len(r)):
        k = int(path.n_returns[i])
        if k < 20:
            assert math.isnan(path.next_var[i])
        else:
            assert path.next_var[i] == pytest.approx(expected_after[k], rel=1e-14)


def test_ewma_validates_lambda() -> None:
    with pytest.raises(ValueError):
        ewma_path([0.01], 1.0)


# --- 4. GARCH ---------------------------------------------------------------------------------


def _reference_garch_forecast(
    var_t: float, omega: float, alpha: float, beta: float, horizon: int
) -> np.ndarray:
    """Cópia literal de `garch_forecast` da referência técnica (§6, eqs. 4.5 e 4.9)."""
    v_long = omega / (1 - alpha - beta)
    tau = np.arange(1, horizon + 1)
    return v_long + (alpha + beta) ** tau * (var_t - v_long)


@pytest.mark.parametrize("horizon", [1, 5, 21, 63, 252])
@pytest.mark.parametrize("var_t", [1e-5, 8.016e-5, 4e-4])
def test_garch_term_variance_matches_reference(var_t: float, horizon: int) -> None:
    omega, alpha, beta = 5.05e-6, 0.053, 0.884
    # A referência parte de σ²ₜ; aqui partimos de σ²ₜ₊₁ = E[σ²ₜ₊₁ | σ²ₜ] = V + (α + β)(σ²ₜ − V).
    v_long = omega / (1 - alpha - beta)
    next_var = v_long + (alpha + beta) * (var_t - v_long)
    expected = float(np.mean(_reference_garch_forecast(var_t, omega, alpha, beta, horizon)))
    assert garch_term_variance(next_var, omega, alpha, beta, horizon) == pytest.approx(expected, rel=1e-12)


def test_garch_long_run_vol_msft_case() -> None:
    """§7 da referência: ω = 5,05e-6, α = 0,053, β = 0,884 → vol de longo prazo ≈ 0,142 (0,005)."""
    fit = GarchFit(omega=5.05e-6, alpha=0.053, beta=0.884, next_var=1e-4, n_returns=1000, loglik=0.0)
    assert math.sqrt(fit.long_run_var * ANNUALIZATION) == pytest.approx(0.142, abs=0.005)
    # Horizonte longo converge para V.
    long_h = garch_term_variance(fit.next_var, fit.omega, fit.alpha, fit.beta, 100_000)
    assert long_h == pytest.approx(fit.long_run_var, rel=1e-3)


def _simulate_garch(n: int, omega: float, alpha: float, beta: float, *, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(n + 500)
    v = omega / (1 - alpha - beta)
    out = np.empty(n + 500)
    for i in range(n + 500):
        out[i] = math.sqrt(v) * z[i]
        v = omega + alpha * out[i] ** 2 + beta * v
    return out[500:]


def test_garch_recovers_parameters_on_synthetic_series() -> None:
    """Tolerância documentada: com 5.000 retornos o erro de α e β fica abaixo de 0,03 e a vol de
    longo prazo dentro de 10% (o estimador é consistente; com 250 pontos seria bem pior, LC-04)."""
    omega, alpha, beta = 4e-6, 0.08, 0.90
    r = _simulate_garch(5000, omega, alpha, beta, seed=11)
    fit = fit_garch(r, min_returns=240)
    assert isinstance(fit, GarchFit)
    assert fit.alpha == pytest.approx(alpha, abs=0.03)
    assert fit.beta == pytest.approx(beta, abs=0.03)
    true_lr = math.sqrt(omega / (1 - alpha - beta) * ANNUALIZATION)
    assert math.sqrt(fit.long_run_var * ANNUALIZATION) == pytest.approx(true_lr, rel=0.10)
    assert fit.n_returns == 5000


def test_garch_minimum_sample_and_validation() -> None:
    short = fit_garch(_returns(100, 0.02, 1), min_returns=240)
    assert isinstance(short, GarchFailure) and "mínimo de 240" in short.reason
    with pytest.raises(ValueError):
        fit_garch(np.array([0.01] * 239 + [np.nan]), min_returns=10)
    with pytest.raises(ValueError):
        garch_term_variance(1e-4, 1e-6, 0.5, 0.5, 21)


# --- 5. Métricas ------------------------------------------------------------------------------


def test_realized_vol_window() -> None:
    r = np.array([np.nan, 0.01, -0.02, 0.03, np.nan, 0.01])
    assert realized_vol(r, 0, 3) == pytest.approx(math.sqrt(252 / 3 * (0.01**2 + 0.02**2 + 0.03**2)))
    assert realized_vol(r, 1, 3) is None  # janela 2..4 inclui um pregão sem retorno
    assert realized_vol(r, 4, 3) is None  # janela além do fim


def test_error_metrics_by_hand() -> None:
    f = [0.30, 0.25, 0.40]
    rv = [0.20, 0.30, 0.35]
    m = error_metrics(f, rv)
    # e = 0,10; −0,05; 0,05
    assert m.n == 3
    assert m.bias == pytest.approx(0.10 / 3)
    assert m.mae == pytest.approx(0.20 / 3)
    assert m.rmse == pytest.approx(math.sqrt((0.01 + 0.0025 + 0.0025) / 3))


def test_rmse_ratio_and_bootstrap_are_deterministic() -> None:
    rng = np.random.default_rng(5)
    rv = 0.3 + 0.05 * rng.standard_normal(12)
    good = rv + 0.01 * rng.standard_normal(12)
    bad = rv + 0.08 * rng.standard_normal(12)
    value, ci = rmse_ratio(good, bad, rv, reps=2000, level=0.9, seed=1)
    expected = math.sqrt(np.mean((good - rv) ** 2)) / math.sqrt(np.mean((bad - rv) ** 2))
    assert value == pytest.approx(expected)
    assert ci.low <= value <= ci.high
    assert rmse_ratio(good, bad, rv, reps=2000, level=0.9, seed=1)[1] == ci
    rci = rmse_interval(good, rv, reps=2000, level=0.9, seed=1)
    assert rci.low <= math.sqrt(np.mean((good - rv) ** 2)) <= rci.high


# --- 6. Intervalos ----------------------------------------------------------------------------


@pytest.mark.parametrize("horizon", [5, 21, 63])
def test_chi2_forecast_interval_coverage(horizon: int) -> None:
    """Com o modelo correto (σ̂ = σ), a RV realizada cai no intervalo de 90% em ~90% das janelas
    (tolerância: 1,5 ponto com 40.000 janelas simuladas)."""
    sigma = 0.30
    rng = np.random.default_rng(horizon)
    r = rng.standard_normal((40_000, horizon)) * sigma / math.sqrt(ANNUALIZATION)
    rv = np.sqrt(ANNUALIZATION / horizon * np.sum(r * r, axis=1))
    ci = chi2_forecast_interval(sigma, horizon, 0.90)
    coverage = float(np.mean((rv >= ci.low) & (rv <= ci.high)))
    assert coverage == pytest.approx(0.90, abs=0.015)


@pytest.mark.parametrize("n", [20, 60])
def test_chi2_vol_interval_coverage(n: int) -> None:
    sigma_daily = 0.02
    rng = np.random.default_rng(n)
    r = rng.standard_normal((40_000, n)) * sigma_daily
    s = np.sqrt(np.mean(r * r, axis=1))  # média zero, dof = n
    lo = s * math.sqrt(n / float(_chi2_hi(n)))
    hi = s * math.sqrt(n / float(_chi2_lo(n)))
    coverage = float(np.mean((sigma_daily >= lo) & (sigma_daily <= hi)))
    assert coverage == pytest.approx(0.90, abs=0.015)
    ci = chi2_vol_interval(0.25, n, 0.90)
    assert ci.low < 0.25 < ci.high


def _chi2_lo(dof: int) -> float:
    from scipy.stats import chi2

    return float(chi2.ppf(0.05, dof))


def _chi2_hi(dof: int) -> float:
    from scipy.stats import chi2

    return float(chi2.ppf(0.95, dof))


def test_empirical_interval_from_log_errors() -> None:
    f = np.full(9, 0.30)
    rv = 0.30 * np.exp(np.linspace(-0.4, 0.4, 9))
    q = log_error_quantiles(f, rv, 0.90)
    assert q.low == pytest.approx(-0.4 + 0.8 * 0.05) and q.high == pytest.approx(0.4 - 0.8 * 0.05)
    ci = empirical_forecast_interval(0.25, q)
    assert ci.low == pytest.approx(0.25 * math.exp(q.low)) and ci.high == pytest.approx(
        0.25 * math.exp(q.high)
    )


def test_combination_requires_core_estimators() -> None:
    core = [np.array([1.0, 2.0, np.nan]), np.array([3.0, 4.0, 5.0]), np.array([5.0, 6.0, 7.0])]
    intraday = np.array([np.nan, 8.0, 9.0])
    var, count = combination_variance(core, [intraday])
    assert var[0] == pytest.approx(3.0) and count[0] == 3
    assert var[1] == pytest.approx(5.0) and count[1] == 4
    assert math.isnan(var[2]) and count[2] == 0
