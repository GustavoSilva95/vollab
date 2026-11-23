"""IV de referência, sincronização, ATM, prazo constante e salto de evento (RN-VOL-03..06, RN-EVT-01..03)."""

import math

import numpy as np
import pytest

from vollab.quant.implied import (
    SmilePoint,
    TermPoint,
    atm_iv,
    constant_maturity,
    event_expected_move,
    event_vol,
    forward_vol,
    historical_jump,
    reference_iv,
    synchronize,
)


def test_sync_uses_last_underlying_trade_up_to_option_time() -> None:
    und = [100.0, 105.0, 105.0, 120.0]
    res = synchronize([99.0, 105.0, 110.0, 131.0], und, max_lag_s=10.0)
    assert list(res.underlying_index) == [-1, 2, 2, 3]
    assert np.isnan(res.lag_s[0])
    assert list(res.lag_s[1:]) == [0.0, 5.0, 11.0]
    assert list(res.synced) == [False, True, True, False]  # 11 s > janela de 10 s


def test_sync_rejects_unsorted_underlying() -> None:
    with pytest.raises(ValueError):
        synchronize([1.0], [2.0, 1.0], max_lag_s=10)


def test_reference_iv_median_of_last_hour() -> None:
    t = [100.0, 61000.0, 62000.0, 63000.0, 64000.0]
    iv = [0.9, 0.30, 0.32, np.nan, 0.31]
    ref = reference_iv(t, iv, window_start_s=61200.0 - 3600, min_trades=3)
    assert ref.status == "ok"
    assert ref.iv == pytest.approx(0.31)
    assert ref.trades_used == 3


def test_reference_iv_low_sample_uses_last_synced() -> None:
    ref = reference_iv([100.0, 200.0, 61000.0], [0.4, 0.5, np.nan], window_start_s=60000.0, min_trades=3)
    assert ref.status == "low_sample"
    assert ref.iv == 0.5
    assert reference_iv([1.0], [np.nan], window_start_s=0, min_trades=3).status == "no_iv"


def test_atm_interpolates_in_log_moneyness_with_otm_side() -> None:
    pts = [
        SmilePoint(28.0, 0.40, False),
        SmilePoint(28.0, 0.99, True),  # call ITM ignorada: há a put OTM no mesmo strike
        SmilePoint(32.0, 0.30, True),
        SmilePoint(36.0, 0.25, True),
    ]
    res = atm_iv(pts, 30.0, k_min=0.9, k_max=1.1)
    w = (0 - math.log(28 / 30)) / (math.log(32 / 30) - math.log(28 / 30))
    assert res.iv == pytest.approx((1 - w) * 0.40 + w * 0.30)
    assert (res.lower_strike, res.upper_strike) == (28.0, 32.0)


def test_atm_unavailable_without_both_sides() -> None:
    res = atm_iv([SmilePoint(31.0, 0.3, True), SmilePoint(32.0, 0.3, True)], 30.0, k_min=0.9, k_max=1.1)
    assert res.iv is None
    assert res.reason is not None


def test_constant_maturity_interpolates_total_variance() -> None:
    t1, t2, target = 10 / 252, 31 / 252, 21 / 252
    res = constant_maturity([TermPoint(t1, 0.40), TermPoint(t2, 0.30)], target)
    a = (t2 - target) / (t2 - t1)
    expected = math.sqrt((a * 0.16 * t1 + (1 - a) * 0.09 * t2) / target)
    assert res.iv == pytest.approx(expected)


def test_constant_maturity_never_extrapolates() -> None:
    res = constant_maturity([TermPoint(25 / 252, 0.4), TermPoint(45 / 252, 0.3)], 21 / 252)
    assert res.iv is None
    assert "extrapola" in (res.reason or "")
    assert constant_maturity([TermPoint(25 / 252, 0.4)], 21 / 252).iv is None


def test_constant_maturity_ex_event_removes_jump_variance() -> None:
    s1, t1, s2, t2 = 0.45, 10 / 252, 0.35, 31 / 252
    se = event_vol(s1, t1, s2, t2)
    assert se is not None
    adj = se * se
    res = constant_maturity([TermPoint(t1, s1, adj), TermPoint(t2, s2, adj)], 21 / 252)
    # Com um único evento antes de t1, a vol ex-evento é a vol a termo "normal" (eq. 5.2/5.3).
    normal = forward_vol(s1, t1, s2, t2)
    assert normal is not None
    assert res.iv == pytest.approx(normal, rel=1e-12)


def test_event_expected_move_reference_case() -> None:
    """Referência técnica §7: 45%/10d e 35%/38d (dias/365) → ≈ 0,0435."""
    assert event_expected_move(0.45, 10 / 365, 0.35, 38 / 365) == pytest.approx(0.0435, abs=5e-4)
    assert event_vol(0.30, 0.1, 0.35, 0.2) is None  # σ1 ≤ σ2: sem salto precificado


def test_historical_jump_subtracts_normal_variance_and_ci_widens_with_few_events() -> None:
    rng = np.random.default_rng(1)
    returns = 0.05 * rng.standard_normal(200)
    normal = (0.25**2) / 252
    big = historical_jump(returns, normal, ci_level=0.9)
    small = historical_jump(returns[:3], normal, ci_level=0.9)
    assert big.value == pytest.approx(math.sqrt(np.mean(returns**2) - normal))
    assert big.ci_low is not None and big.ci_high is not None and big.value is not None
    assert big.ci_low < big.value < big.ci_high
    assert small.ci_high is not None and small.ci_low is not None
    assert (small.ci_high - small.ci_low) > (big.ci_high - big.ci_low)
    assert historical_jump([], normal, ci_level=0.9).value is None
