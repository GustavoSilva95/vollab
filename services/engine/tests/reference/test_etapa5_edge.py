"""Etapa 5 (PRD 1.8 §5.6.1 e §10.2): custos, spread normal, prêmio, edge e semáforo.

Critério de saída do PLANO: semáforo nos três estados, nas duas direções e nos limites; rótulo
"não calibrado". Mais: Leland contra o caso da §7 da referência, estimador de spread e custos do
straddle contra cálculo à mão, unidades (nada em %).
"""

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vollab.quant.costs import (
    Band,
    BandDay,
    SeriesSpread,
    aggregate_band,
    hedge_cost,
    leland_vol,
    moneyness_band,
    quoted_relative_spread,
    series_spread,
    spread_estimate,
    straddle_cost,
)
from vollab.quant.edge import (
    Direction,
    EdgeState,
    Premium,
    classify,
    iv_rank,
    normal_spread,
    premium,
    ranking_key,
)
from vollab.quant.implied import SmilePoint, atm_iv, iv_at_moneyness
from vollab.quant.pricing import bs_greeks

pytestmark = pytest.mark.reference


# --- Leland (eqs. 6.7–6.8; §7 da referência) -------------------------------------------------


def test_leland_reference_case() -> None:
    """§7: σ = 10%, meio spread 0,5%, Δt = 1/365, vendido ≈ 0,159."""
    assert leland_vol(0.10, 0.005, 1 / 365, long=False) == pytest.approx(0.159, abs=5e-4)
    a = (0.005 / 0.10) * math.sqrt(8 / (math.pi / 365))
    assert leland_vol(0.10, 0.005, 1 / 365, long=False) == pytest.approx(0.10 * math.sqrt(1 + a), rel=1e-15)


def test_leland_long_infeasible_when_cost_exceeds_vol() -> None:
    assert leland_vol(0.10, 0.005, 1 / 365, long=True) is None  # a ≈ 1,52 ≥ 1
    assert leland_vol(0.10, 0.0, 1 / 252, long=True) == pytest.approx(0.10)


def test_hedge_cost_uses_half_spread_plus_fee() -> None:
    h = hedge_cost(0.30, underlying_rel_spread=0.0004, fee_rate=0.0003, interval_bd=1)
    lam = 0.0002 + 0.0003
    a = lam / 0.30 * math.sqrt(8 / (math.pi / 252))
    assert h.half_spread == pytest.approx(lam)
    assert h.sell == pytest.approx(0.30 * (math.sqrt(1 + a) - 1))
    assert h.buy == pytest.approx(0.30 * (1 - math.sqrt(1 - a)))
    assert h.buy is not None and h.buy > h.sell > 0  # comprado custa mais em vol (concavidade da raiz)


# --- Spread estimado (RN-CST-03) -------------------------------------------------------------


def test_series_spread_by_hand() -> None:
    prices = [1.00, 1.02, 1.00, 1.02, 1.02, 1.05, 1.02]  # trocas: 0,02 0,02 0,02 0,03 0,03
    est = series_spread(prices, floor_brl=0.01, min_trades=5)
    assert est is not None
    assert est.spread_brl == pytest.approx(0.02)
    assert est.relative == pytest.approx(0.02 / 1.02)
    assert (est.trades, est.price_changes, est.floored) == (7, 5, False)


def test_series_spread_floor_and_minimum() -> None:
    flat = series_spread([2.0] * 30, floor_brl=0.01, min_trades=20)
    assert flat is not None and flat.spread_brl == 0.01 and flat.floored  # sem troca: o tick
    tiny = series_spread([1.0, 1.001] * 15, floor_brl=0.01, min_trades=20)
    assert tiny is not None and tiny.spread_brl == 0.01 and tiny.floored
    assert series_spread([1.0, 1.01] * 9, floor_brl=0.01, min_trades=20) is None  # 18 < 20
    assert series_spread([1.0, 0.0, 1.0], floor_brl=0.01, min_trades=2) is None


def test_moneyness_bands_and_quoted() -> None:
    bands = (0.95, 1.05)
    assert moneyness_band(0.9499, bands) is Band.LOW
    assert moneyness_band(0.95, bands) is Band.ATM
    assert moneyness_band(1.05, bands) is Band.ATM
    assert moneyness_band(1.0501, bands) is Band.HIGH
    assert quoted_relative_spread(1.00, 1.04, 1.02) == pytest.approx(0.04 / 1.02)
    assert quoted_relative_spread(0.0, 1.04, 1.02) is None
    assert quoted_relative_spread(1.04, 1.00, 1.02) is None


def test_spread_estimate_central_conservative_and_quoted_only_as_check() -> None:
    s = [SeriesSpread(0.01, r, 30, 10, False) for r in (0.01, 0.02, 0.03, 0.04)]
    day = aggregate_band(s, [0.50])
    assert day.rel_median == pytest.approx(0.025)
    assert day.rel_p75 == pytest.approx(0.0325)
    days = [day, BandDay(3, 90, 0.015, 0.02, None), BandDay(0, 0, None, None, None)]
    est = spread_estimate(days)
    assert est is not None
    assert est.central == pytest.approx(0.02)  # mediana de 0,025 e 0,015
    assert est.conservative == pytest.approx((0.0325 + 0.02) / 2)  # mediana dos p75
    assert est.quoted == pytest.approx(0.50)  # PRD 1.8.1: fora do custo
    assert (est.days, est.n_series) == (2, 7)
    assert spread_estimate([BandDay(0, 0, None, None, None)]) is None


# --- Custo do straddle em pontos de vol ------------------------------------------------------


def test_straddle_cost_by_hand() -> None:
    spot, t, r, iv, pvd = 30.0, 21 / 252, math.log(1.15), 0.32, 0.5
    c = straddle_cost(
        spot=spot,
        t=t,
        rate_c=r,
        iv=iv,
        pv_div=pvd,
        option_rel_spread=0.012,
        fee_rate=0.00134,
        brokerage_rate=0.001,
        brokerage_per_order_brl=5.0,
        reference_contracts=100,
    )
    f = (spot - pvd) * math.exp(r * t)
    g = bs_greeks([spot, spot], [f, f], t, r, iv, [True, False], pvd)
    prem = float(g.price.sum())
    vega = float(g.vega_per_point.sum()) * 100
    assert c.premium_brl == pytest.approx(prem)
    assert c.vega_brl == pytest.approx(vega)
    expected = 0.012 * prem + 2 * 0.00134 * prem + 2 * 0.001 * prem + 4 * 5.0 / 100
    assert c.total_brl == pytest.approx(expected)
    assert c.vol_points == pytest.approx(expected / vega)
    # ATM: prêmio ≈ 0,8·S*·σ√t e vega ≈ 0,8·S*·√t ⇒ custo proporcional ≈ taxa × σ (unidades decimais).
    no_fixed = straddle_cost(
        spot=spot,
        t=t,
        rate_c=r,
        iv=iv,
        pv_div=pvd,
        option_rel_spread=0.0,
        fee_rate=0.001,
        brokerage_rate=0.0,
        brokerage_per_order_brl=0.0,
        reference_contracts=100,
    )
    assert no_fixed.vol_points == pytest.approx(2 * 0.001 * iv, rel=0.02)


# --- Spread normal (QA-14) e IV rank ---------------------------------------------------------


def test_normal_spread_median_and_uncalibrated_cut() -> None:
    iv = [0.30, 0.33, 0.25, 0.40, 0.36, 0.28, 0.31, 0.35]
    rv = [0.25, 0.30, 0.25, 0.32, 0.30, 0.28, 0.25, 0.30]
    x = sorted((a - b) / b for a, b in zip(iv, rv, strict=True))
    ns = normal_spread(iv, rv, min_pairs=8, default=0.15, reps=500, level=0.9)
    assert ns.calibrated and ns.n_pairs == 8
    assert ns.value == pytest.approx((x[3] + x[4]) / 2)
    assert ns.ci_low is not None and ns.ci_high is not None and ns.ci_low <= ns.value <= ns.ci_high
    again = normal_spread(iv, rv, min_pairs=8, default=0.15, reps=500, level=0.9)
    assert (again.ci_low, again.ci_high) == (ns.ci_low, ns.ci_high)  # semente fixa
    short = normal_spread(iv[:7], rv[:7], min_pairs=8, default=0.15, reps=500, level=0.9)
    assert (short.value, short.calibrated, short.n_pairs, short.ci_low) == (0.15, False, 7, None)
    # Nunca zero implícito: sem nenhum par, vale o padrão configurado.
    none = normal_spread([], [], min_pairs=8, default=0.15, reps=500, level=0.9)
    assert none.value == 0.15 and not none.calibrated


def test_iv_rank() -> None:
    hist = [0.20 + 0.001 * i for i in range(100)]
    r = iv_rank(hist, 0.25, min_days=60)
    assert r.rank == pytest.approx((0.25 - 0.20) / (0.299 - 0.20))
    assert r.percentile == pytest.approx(51 / 100)
    assert iv_rank(hist[:59], 0.25, min_days=60).rank is None
    assert iv_rank(hist, 0.50, min_days=60).rank == 1.0


def test_iv_at_moneyness_matches_atm_and_interpolates() -> None:
    f = 100.0
    pts = [
        SmilePoint(90, 0.36, False),
        SmilePoint(95, 0.33, False),
        SmilePoint(100, 0.30, True),
        SmilePoint(105, 0.28, True),
        SmilePoint(110, 0.27, True),
    ]
    assert iv_at_moneyness(pts, f, 1.0, k_min=0.9, k_max=1.1).iv == atm_iv(pts, f, k_min=0.9, k_max=1.1).iv
    assert iv_at_moneyness(pts, f, 0.95, k_min=0.9, k_max=1.1).iv == pytest.approx(0.33)
    mid = iv_at_moneyness(pts, f, 1.075, k_min=0.9, k_max=1.1)
    w = (math.log(1.075) - math.log(1.05)) / (math.log(1.10) - math.log(1.05))
    assert mid.iv == pytest.approx((1 - w) * 0.28 + w * 0.27)
    assert iv_at_moneyness(pts, f, 0.85, k_min=0.9, k_max=1.1).iv is None  # sem extrapolação


# --- Prêmio, edge relativo e semáforo (RN-EDG-01..05) ----------------------------------------


def test_premium_and_relative_edge_definitions() -> None:
    p = premium(0.36, 0.30, 0.26, 0.35, 0.15)
    assert p.value == pytest.approx(0.36 - 0.30 * 1.15)
    assert (p.ci_low, p.ci_high) == pytest.approx((0.36 - 0.35 * 1.15, 0.36 - 0.26 * 1.15))
    # Edge relativo = (IV − σ̂)/σ̂ − s = p/σ̂: as duas métricas têm sempre o mesmo sinal.
    assert p.value / 0.30 == pytest.approx((0.36 - 0.30) / 0.30 - 0.15)


def _p(lo: float, hi: float) -> Premium:
    return Premium((lo + hi) / 2, lo, hi)


@pytest.mark.parametrize(
    ("lo", "hi", "state", "direction"),
    [
        (0.05, 0.10, EdgeState.EDGE, Direction.SELL),  # limite inferior acima de c_v + L = 0,03
        (-0.10, -0.05, EdgeState.EDGE, Direction.BUY),  # limite superior abaixo de −(c_c + L) = −0,04
        (-0.02, 0.02, EdgeState.NO_EDGE, Direction.SELL),  # intervalo entre os dois níveis
        (0.01, 0.06, EdgeState.INCONCLUSIVE, Direction.SELL),  # contém o nível de venda
        (-0.06, -0.01, EdgeState.INCONCLUSIVE, Direction.BUY),  # contém o nível de compra
        (-0.06, 0.06, EdgeState.INCONCLUSIVE, Direction.SELL),  # contém os dois
    ],
)
def test_traffic_light_three_states_both_directions(
    lo: float, hi: float, state: EdgeState, direction: Direction
) -> None:
    sig = classify(_p(lo, hi), forecast=0.30, cost_sell=0.02, cost_buy=0.03, threshold=0.01)
    assert (sig.state, sig.direction) == (state, direction)
    assert sig.required_sell == pytest.approx(0.03)
    assert sig.required_buy == pytest.approx(0.04)


def test_traffic_light_limits_are_strict() -> None:
    """Empate nunca dá edge líquido: p_lo = N_v e p_hi = −N_c ficam inconclusivos; um ulp além vira
    edge. Na borda de 'sem edge', p_hi = N_v e p_lo = −N_c ainda são 'sem edge'."""
    nv, nc = 0.02 + 0.01, 0.03 + 0.01
    kw = {"forecast": 0.30, "cost_sell": 0.02, "cost_buy": 0.03, "threshold": 0.01}
    assert classify(_p(nv, nv + 0.05), **kw).state is EdgeState.INCONCLUSIVE
    assert classify(_p(math.nextafter(nv, 1), nv + 0.05), **kw).state is EdgeState.EDGE
    assert classify(_p(-nc - 0.05, -nc), **kw).state is EdgeState.INCONCLUSIVE
    assert classify(_p(-nc - 0.05, math.nextafter(-nc, -1)), **kw).state is EdgeState.EDGE
    assert classify(_p(-nc, nv), **kw).state is EdgeState.NO_EDGE
    assert classify(_p(-nc, math.nextafter(nv, 1)), **kw).state is EdgeState.INCONCLUSIVE
    assert classify(_p(math.nextafter(-nc, -1), nv), **kw).state is EdgeState.INCONCLUSIVE


def test_buy_infeasible_when_hedge_consumes_everything() -> None:
    sig = classify(_p(-0.50, -0.40), forecast=0.30, cost_sell=0.02, cost_buy=None, threshold=0.01)
    # Nunca edge de compra; como a venda também não paga, nenhuma direção paga os custos: sem edge.
    assert sig.state is EdgeState.NO_EDGE
    assert sig.required_buy is None and sig.net_relative is None and sig.net_premium is None


def test_net_relative_edge_and_ranking_order() -> None:
    sell = classify(_p(0.05, 0.10), forecast=0.30, cost_sell=0.02, cost_buy=0.03, threshold=0.01)
    assert sell.net_premium == pytest.approx(0.075 - 0.02)
    assert sell.net_relative == pytest.approx((0.075 - 0.02) / 0.30)
    buy = classify(_p(-0.10, -0.05), forecast=0.30, cost_sell=0.02, cost_buy=0.03, threshold=0.01)
    assert buy.net_premium == pytest.approx(0.075 - 0.03)
    rows = [
        (EdgeState.NO_EDGE, 0.5, "A"),
        (EdgeState.EDGE, 0.1, "B"),
        (EdgeState.UNAVAILABLE, None, "C"),
        (EdgeState.EDGE, 0.3, "D"),
        (EdgeState.INCONCLUSIVE, 0.9, "E"),
        (EdgeState.EDGE, 0.3, "AA"),
    ]
    ordered = [r[2] for r in sorted(rows, key=lambda r: ranking_key(*r))]
    assert ordered == ["AA", "D", "B", "E", "A", "C"]


_STATE_RANK = {EdgeState.EDGE: 0, EdgeState.INCONCLUSIVE: 1, EdgeState.NO_EDGE: 2}


@settings(max_examples=300, deadline=None)
@given(
    lo=st.floats(-0.5, 0.5),
    width=st.floats(0.0, 0.5),
    cs=st.floats(0.0, 0.1),
    cb=st.floats(0.0, 0.1),
    thr=st.floats(0.0, 0.05),
    extra=st.floats(0.0, 0.1),
)
def test_more_cost_or_threshold_never_improves_the_state(
    lo: float, width: float, cs: float, cb: float, thr: float, extra: float
) -> None:
    """Monotonicidade: subir custos ou o limiar nunca leva de 'sem edge'/'inconclusivo' a 'edge', nem
    troca a direção de um edge líquido."""
    p = _p(lo, lo + width)
    base = classify(p, forecast=0.3, cost_sell=cs, cost_buy=cb, threshold=thr)
    for worse in (
        classify(p, forecast=0.3, cost_sell=cs + extra, cost_buy=cb, threshold=thr),
        classify(p, forecast=0.3, cost_sell=cs, cost_buy=cb + extra, threshold=thr),
        classify(p, forecast=0.3, cost_sell=cs, cost_buy=cb, threshold=thr + extra),
    ):
        if worse.state is EdgeState.EDGE:
            assert base.state is EdgeState.EDGE and base.direction is worse.direction
        if base.state is EdgeState.NO_EDGE:
            assert worse.state is EdgeState.NO_EDGE  # níveis mais largos: continua dentro


@settings(max_examples=200, deadline=None)
@given(iv=st.floats(0.05, 1.5), f=st.floats(0.05, 1.5), s=st.floats(-0.3, 0.6))
def test_units_are_decimal(iv: float, f: float, s: float) -> None:
    """T-REF-06 para a Etapa 5: entradas e saídas em decimal; nada em percentual."""
    p = premium(iv, f, f * 0.8, f * 1.2, s)
    assert abs(p.value) < 3  # pontos de vol em decimal (3 = 300 pontos), nunca 30 ou 300
    assert np.isfinite(p.value / f)
