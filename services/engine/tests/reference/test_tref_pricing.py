"""T-REF-01..04 (PRD §10.2): Black-Scholes com dividendos discretos, IV, paridade e Greeks.

Referências publicadas (precisão em que foram publicadas):
- Hull, *Options, Futures and Other Derivatives*, ex. 15.6: S=42, K=40, r=10%, σ=20%, T=0,5 →
  call 4,76, put 0,81.
- Hull, ex. 15.10 (dividendos discretos): S=40, K=40, proventos de 0,50 em 2 e 5 meses, T=0,5,
  r=9%, σ=30% → call 3,67.
- Haug, *The Complete Guide to Option Pricing Formulas*, 2ª ed., §1.1.1: S=60, K=65, T=0,25,
  r=8%, σ=30% → call 2,1334.
A precisão de 1e-8 é verificada contra uma implementação independente em mpmath (40 dígitos).
"""

import math

import mpmath as mp  # type: ignore[import-untyped]
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vollab.quant.pricing import (
    BUSINESS_DAYS_PER_YEAR,
    Dividend,
    IvStatus,
    bs_greeks,
    bs_price,
    continuous_rate,
    implied_vol,
    pv_dividends,
    years_from_business_days,
)

pytestmark = pytest.mark.reference

mp.mp.dps = 40


def _mp_price(s: float, k: float, t: float, r: float, sigma: float, call: bool, pvd: float = 0.0) -> float:
    ss = mp.mpf(s) - mp.mpf(pvd)
    kk, tt, rr, vv = mp.mpf(k), mp.mpf(t), mp.mpf(r), mp.mpf(sigma)
    d1 = (mp.log(ss / kk) + (rr + vv * vv / 2) * tt) / (vv * mp.sqrt(tt))
    d2 = d1 - vv * mp.sqrt(tt)
    if call:
        return float(ss * mp.ncdf(d1) - kk * mp.e ** (-rr * tt) * mp.ncdf(d2))
    return float(kk * mp.e ** (-rr * tt) * mp.ncdf(-d2) - ss * mp.ncdf(-d1))


# --- T-REF-01 --------------------------------------------------------------------------------


def test_tref01_hull_15_6() -> None:
    assert float(bs_price(42, 40, 0.5, 0.10, 0.20, True)) == pytest.approx(4.76, abs=0.005)
    assert float(bs_price(42, 40, 0.5, 0.10, 0.20, False)) == pytest.approx(0.81, abs=0.005)


def test_tref01_haug_1_1_1() -> None:
    assert float(bs_price(60, 65, 0.25, 0.08, 0.30, True)) == pytest.approx(2.1334, abs=5e-5)


def test_tref01_hull_15_10_discrete_dividends() -> None:
    divs = [Dividend(2 / 12, 0.5), Dividend(5 / 12, 0.5)]
    pvd = pv_dividends(divs, 0.5, 0.09)
    assert pvd == pytest.approx(0.9742, abs=1e-4)  # Hull: 0,9742
    assert float(bs_price(40, 40, 0.5, 0.09, 0.30, True, pvd)) == pytest.approx(3.67, abs=0.005)


@pytest.mark.parametrize(
    ("s", "k", "t", "r", "sigma", "pvd"),
    [
        (42, 40, 0.5, 0.10, 0.20, 0.0),
        (60, 65, 0.25, 0.08, 0.30, 0.0),
        (40, 40, 0.5, 0.09, 0.30, 0.974_119_6),
        (30.36, 28.0, 21 / 252, math.log1p(0.149), 0.35, 0.0),
        (30.36, 33.0, 42 / 252, math.log1p(0.149), 0.28, 0.65),
        (130.0, 120.0, 2.0, 0.12, 0.55, 3.2),
        (10.0, 10.0, 1 / 252, 0.15, 0.80, 0.0),
    ],
)
def test_tref01_against_mpmath(s: float, k: float, t: float, r: float, sigma: float, pvd: float) -> None:
    for call in (True, False):
        got = float(bs_price(s, k, t, r, sigma, call, pvd))
        assert abs(got - _mp_price(s, k, t, r, sigma, call, pvd)) < 1e-8


def test_pv_dividends_only_inside_horizon() -> None:
    divs = [Dividend(0.0, 1.0), Dividend(0.1, 1.0), Dividend(0.6, 1.0)]
    assert pv_dividends(divs, 0.5, 0.1) == pytest.approx(math.exp(-0.01))


# --- T-REF-02 --------------------------------------------------------------------------------


@settings(max_examples=400, deadline=None)
@given(
    moneyness=st.floats(0.6, 1.6),
    days=st.integers(1, 504),
    sigma=st.floats(0.03, 2.0),
    rate=st.floats(0.0, 0.20),
    call=st.booleans(),
    div_frac=st.floats(0.0, 0.05),
)
def test_tref02_iv_round_trip(
    moneyness: float, days: int, sigma: float, rate: float, call: bool, div_frac: float
) -> None:
    s, t = 100.0, days / BUSINESS_DAYS_PER_YEAR
    k = s * moneyness
    pvd = s * div_frac
    price = float(bs_price(s, k, t, rate, sigma, call, pvd))
    greeks = bs_greeks(s, k, t, rate, sigma, call, pvd)
    res = implied_vol(price, s, k, t, rate, call, pvd)
    vega_rel = float(greeks.vega_per_point) * 100.0 / s
    if vega_rel >= 1e-4:
        # Onde a vega é relevante: IV volta a sigma com erro < 1e-6.
        assert int(res.status) == IvStatus.OK
        assert abs(float(res.iv) - sigma) < 1e-6
    elif int(res.status) == IvStatus.OK:
        # Vega desprezível: o preço quase não depende de sigma; exige-se só reprecificar.
        repriced = float(bs_price(s, k, t, rate, float(res.iv), call, pvd))
        assert abs(repriced - price) < 1e-9 * s
    else:
        assert math.isnan(float(res.iv))


@pytest.mark.parametrize("call", [False, True])
def test_tref02_regression_exact_newton_hit(call: bool) -> None:
    """Caso achado pelo hypothesis na Etapa 6: o Newton acertava a raiz exatamente, o passo seguinte
    virava bisseção e a IV voltava como o ponto médio do intervalo (0,50005) com status OK."""
    s, k, t, r = 100.0, 60.0, 177 / BUSINESS_DAYS_PER_YEAR, 0.13771824977854064
    price = float(bs_price(s, k, t, r, 1.0, call))
    res = implied_vol(price, s, k, t, r, call)
    assert int(res.status) == IvStatus.OK
    assert abs(float(res.iv) - 1.0) < 1e-6


def test_tref02_explicit_failure_without_number() -> None:
    s, k, t, r = 100.0, 90.0, 0.25, 0.10
    intrinsic = s - k * math.exp(-r * t)
    res = implied_vol([intrinsic - 0.01, s + 1.0, 0.0, 5.0], s, k, [t, t, t, 0.0], r, True)
    assert list(res.status) == [
        IvStatus.BELOW_INTRINSIC,
        IvStatus.ABOVE_UPPER_BOUND,
        IvStatus.INVALID_INPUT,
        IvStatus.INVALID_INPUT,
    ]
    assert np.isnan(res.iv).all()


def test_tref02_vectorized_matches_scalar() -> None:
    rng = np.random.default_rng(7)
    n = 2000
    s = rng.uniform(20, 40, n)
    k = s * rng.uniform(0.85, 1.15, n)
    t = rng.integers(2, 120, n) / 252
    sig = rng.uniform(0.15, 0.9, n)
    call = rng.random(n) < 0.5
    prices = bs_price(s, k, t, 0.14, sig, call)
    res = implied_vol(prices, s, k, t, 0.14, call)
    ok = res.status == IvStatus.OK
    assert ok.mean() > 0.99
    assert np.max(np.abs(res.iv[ok] - sig[ok])) < 1e-6


# --- T-REF-03 --------------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    moneyness=st.floats(0.5, 1.5),
    days=st.integers(1, 504),
    sigma=st.floats(0.05, 1.5),
    rate=st.floats(0.0, 0.20),
    div_amounts=st.lists(st.floats(0.0, 1.5), max_size=3),
)
def test_tref03_put_call_parity_with_discrete_dividends(
    moneyness: float, days: int, sigma: float, rate: float, div_amounts: list[float]
) -> None:
    s, t = 50.0, days / BUSINESS_DAYS_PER_YEAR
    k = s * moneyness
    divs = [Dividend(t * (i + 1) / (len(div_amounts) + 1), d) for i, d in enumerate(div_amounts)]
    pvd = pv_dividends(divs, t, rate)
    c = float(bs_price(s, k, t, rate, sigma, True, pvd))
    p = float(bs_price(s, k, t, rate, sigma, False, pvd))
    assert abs((c - p) - (s - pvd - k * math.exp(-rate * t))) < 1e-8


# --- T-REF-04 --------------------------------------------------------------------------------
# Tolerâncias relativas (documentadas): delta, vega e theta 1e-6; gamma 1e-4 (2ª diferença).


@pytest.mark.parametrize("call", [True, False])
@pytest.mark.parametrize(
    ("k", "days", "sigma", "div"),
    [(100, 21, 0.3, 0.0), (95, 63, 0.45, 1.2), (110, 126, 0.25, 2.0), (100, 5, 0.6, 0.0)],
)
def test_tref04_greeks_vs_finite_differences(
    call: bool, k: float, days: int, sigma: float, div: float
) -> None:
    s, r = 100.0, continuous_rate(0.149)
    t = years_from_business_days(days)
    divs = [Dividend(t / 2, div)] if div else []

    def price(spot: float = s, tt: float = t, vol: float = sigma, shift: float = 0.0) -> float:
        moved = [Dividend(d.t_ex - shift, d.amount) for d in divs]
        return float(bs_price(spot, k, tt, r, vol, call, pv_dividends(moved, tt, r)))

    g = bs_greeks(s, k, t, r, sigma, call, pv_dividends(divs, t, r))
    hs = 1e-3
    fd_delta = (price(s + hs) - price(s - hs)) / (2 * hs)
    fd_gamma = (price(s + hs) - 2 * price() + price(s - hs)) / hs**2
    hv = 1e-5
    fd_vega_point = (price(vol=sigma + hv) - price(vol=sigma - hv)) / (2 * hv) / 100.0
    ht = 1e-6
    # Passagem do tempo: prazo e datas ex andam juntos.
    fd_theta_year = (price(tt=t - ht, shift=ht) - price(tt=t + ht, shift=-ht)) / (2 * ht)
    fd_theta_bd = fd_theta_year / BUSINESS_DAYS_PER_YEAR
    assert float(g.delta) == pytest.approx(fd_delta, rel=1e-6)
    assert float(g.gamma) == pytest.approx(fd_gamma, rel=1e-4)
    assert float(g.vega_per_point) == pytest.approx(fd_vega_point, rel=1e-6)
    assert float(g.theta_per_bd) == pytest.approx(fd_theta_bd, rel=1e-6)


# --- T-REF-06 (parte do engine que toca a precificação) ----------------------------------------


def test_tref06_rate_and_time_conventions() -> None:
    # Selic exponencial base 252 → desconto (1 + r)^(−du/252) = e^(−ln(1+r)·t).
    selic = 0.1490
    t = years_from_business_days(21)
    assert t == 21 / 252
    assert math.exp(-continuous_rate(selic) * t) == pytest.approx((1 + selic) ** (-21 / 252), rel=1e-15)
    with pytest.raises(ValueError):
        years_from_business_days(-1)
