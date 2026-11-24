"""Etapa 6 (PRD 1.9 §5.8 e §10.2): simulador e dimensionamento.

T-REF-07 (Kelly e teto em casos montados à mão, igualdade exata) e as propriedades da simulação:
reescala do bootstrap, determinismo pela semente, regra de banda × `rehedge` da referência, venda
coberta sem ajustes, P&L médio do straddle hedgeado × diferença de preço BS, dispersão × banda e
eq. 7.7, payoff no vencimento, stress e ES à mão. Unidades: nada em %.
"""

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vollab.quant.pricing import bs_greeks, bs_price
from vollab.quant.simulation import (
    HedgeRule,
    Leg,
    Market,
    StressScenario,
    Structure,
    expected_shortfall,
    initial_hedge,
    kamal_derman_std,
    payoff_curve,
    rehedge,
    rescale_returns,
    simulate_paths,
    stress_losses,
    structure_greeks,
    structure_iv,
    summarize,
    validate_legs,
)
from vollab.quant.sizing import Rule, SizingInput, size_position

pytestmark = pytest.mark.reference


# --- T-REF-07: Kelly e teto ------------------------------------------------------------------


def _inp(**kw: object) -> SizingInput:
    base: dict[str, object] = {
        "capital": 100_000.0,
        "kelly_fraction": 0.25,
        "max_loss_fraction": 0.07,
        "mu": 200.0,
        "variance": 1_000_000.0,
        "max_loss": 500.0,
        "edge_ok": True,
    }
    return SizingInput(**(base | kw))  # type: ignore[arg-type]


def test_tref07_kelly_prevails() -> None:
    # W·μ/σ² = 100 000·200/1 000 000 = 20 → ¼ → 5 lotes; teto = ⌊7 000/500⌋ = 14.
    s = size_position(_inp())
    assert (s.n_kelly, s.n_cap, s.n_final, s.rule) == (5, 14, 5, Rule.KELLY)
    assert s.kelly_full == 20.0
    assert s.reason is None


def test_tref07_cap_prevails() -> None:
    # μ = 2 000 → W·μ/σ² = 200 → ¼ → 50 lotes; teto 14.
    s = size_position(_inp(mu=2_000.0))
    assert (s.n_kelly, s.n_cap, s.n_final, s.rule) == (50, 14, 14, Rule.CAP)


def test_tref07_tie() -> None:
    # μ = 560 → 56 → ¼ → 14 = teto.
    s = size_position(_inp(mu=560.0))
    assert (s.n_kelly, s.n_cap, s.n_final, s.rule) == (14, 14, 14, Rule.TIE)


def test_tref07_zero_without_edge() -> None:
    s = size_position(_inp(edge_ok=False, zero_reason="semáforo inconclusivo"))
    assert (s.n_kelly, s.n_final, s.rule) == (0, 0, Rule.ZERO)
    assert s.n_cap == 14  # o teto continua informado
    assert s.reason == "semáforo inconclusivo"


def test_tref07_zero_opposite_direction() -> None:
    s = size_position(_inp(edge_ok=False, zero_reason="estrutura vendida com sinal de compra de vol"))
    assert s.n_final == 0 and s.rule is Rule.ZERO and "compra" in (s.reason or "")


@pytest.mark.parametrize("mu", [0.0, -10.0])
def test_tref07_zero_non_positive_mu(mu: float) -> None:
    s = size_position(_inp(mu=mu))
    assert s.n_final == 0 and s.rule is Rule.ZERO


def test_tref07_floor_is_exact_on_decimal_inputs() -> None:
    # Em float, 0,29·100 = 28,999999999999996 → piso 28; o certo é 29.
    s = size_position(_inp(capital=100.0, max_loss_fraction=0.29, max_loss=1.0, mu=1e9, variance=1.0))
    assert s.n_cap == 29 and s.rule is Rule.CAP
    # Kelly exatamente inteiro: ¼·W·μ/σ² = 0,25·1 000·0,3/0,1 = 750.
    s2 = size_position(_inp(capital=1_000.0, mu=0.3, variance=0.1, max_loss=None))
    assert s2.n_kelly == 750 and s2.n_cap is None and s2.rule is Rule.KELLY


def test_tref07_cap_below_one_lot() -> None:
    s = size_position(_inp(max_loss=8_000.0))  # 7 000/8 000 < 1
    assert s.n_final == 0 and s.rule is Rule.CAP and "teto" in (s.reason or "")


def test_tref07_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError):
        size_position(_inp(capital=0.0))
    with pytest.raises(ValueError):
        size_position(_inp(kelly_fraction=1.5))


@settings(max_examples=200, deadline=None)
@given(
    mu=st.floats(1.0, 1e4),
    var=st.floats(1e2, 1e8),
    loss=st.floats(1.0, 1e5),
    cap=st.floats(0.01, 1.0),
)
def test_sizing_never_exceeds_either_limit(mu: float, var: float, loss: float, cap: float) -> None:
    s = size_position(_inp(mu=mu, variance=var, max_loss=loss, max_loss_fraction=cap))
    assert s.n_final <= s.n_kelly
    assert s.n_cap is not None and s.n_final <= s.n_cap
    assert s.n_final * loss <= cap * 100_000.0 * (1 + 1e-12)


# --- ES ----------------------------------------------------------------------------------------


def test_expected_shortfall_by_hand() -> None:
    pnl = np.arange(1000, dtype=float) - 100.0  # piores 10 (1%): −100..−91, média −95,5
    assert expected_shortfall(pnl, 0.99) == pytest.approx(95.5, abs=1e-12)
    assert expected_shortfall(np.array([5.0, 6.0, 7.0]), 0.99) == -5.0  # ⌈0,03⌉ = 1 caminho, lucro


# --- Bootstrap reescalado (QA-10) ---------------------------------------------------------------


def test_rescale_mean_zero_and_exact_vol() -> None:
    rng = np.random.default_rng(1)
    r = rng.standard_t(4, size=252) * 0.02 + 0.001
    z = rescale_returns(r, 0.35)
    assert abs(z.mean()) < 1e-17
    assert math.sqrt(float(np.mean(z * z))) == pytest.approx(0.35 / math.sqrt(252), rel=1e-14)

    # A forma é preservada: assimetria e curtose padronizadas iguais às da amostra original.
    def moments(x: np.ndarray) -> tuple[float, float]:
        c = x - x.mean()
        sd = math.sqrt(float(np.mean(c * c)))
        return float(np.mean(c**3)) / sd**3, float(np.mean(c**4)) / sd**4

    assert moments(z) == pytest.approx(moments(r), rel=1e-10)


def test_rescale_ignores_non_finite_and_rejects_degenerate() -> None:
    z = rescale_returns([0.01, np.nan, -0.02, 0.03], 0.2)
    assert z.size == 3
    with pytest.raises(ValueError):
        rescale_returns([0.01, 0.01, 0.01], 0.2)
    with pytest.raises(ValueError):
        rescale_returns([0.01], 0.2)


# --- Regra de banda (H1; `rehedge` da referência §6) --------------------------------------------


def _rehedge_reference(current_delta: float, center: float, half_width: float) -> float:
    lo, hi = center - half_width, center + half_width
    if current_delta > hi:
        return hi - current_delta
    if current_delta < lo:
        return lo - current_delta
    return 0.0


@settings(max_examples=300, deadline=None)
@given(delta=st.floats(-3, 3), width=st.floats(0, 1))
def test_rehedge_matches_reference(delta: float, width: float) -> None:
    got = float(rehedge(np.array([delta]), width)[0])
    assert got == pytest.approx(_rehedge_reference(delta, 0.0, width), abs=1e-15)
    assert abs(delta + got) <= width + 1e-15


# --- Estruturas e simulação ---------------------------------------------------------------------

S0, T_BD, R_C, IV = 40.0, 63, 0.0, 0.30


def _straddle(sign: int, iv: float = IV, cost: float = 0.0, k: float = S0, t_bd: int = T_BD) -> list[Leg]:
    t = t_bd / 252
    out = []
    for call in (True, False):
        p = float(bs_price(S0, k, t, R_C, iv, call))
        out.append(Leg(is_call=call, strike=k, quantity=sign, iv=iv, price=p, entry_cost_rate=cost))
    return out


def _gaussian_sample(n: int = 4000, seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)


def test_validate_legs() -> None:
    assert validate_legs(Structure.SHORT_STRADDLE, _straddle(-1)) is None
    assert validate_legs(Structure.LONG_STRADDLE, _straddle(1)) is None
    assert validate_legs(Structure.SHORT_STRADDLE, _straddle(1)) is not None  # sinal errado
    put, call = _straddle(-1, k=38.0)[1], _straddle(-1, k=42.0)[0]
    assert validate_legs(Structure.SHORT_STRANGLE, [put, call]) is None
    assert validate_legs(Structure.SHORT_STRANGLE, [_straddle(-1, k=42.0)[1], _straddle(-1, k=38.0)[0]])
    assert validate_legs(Structure.SHORT_STRADDLE, [put, call]) is not None  # strikes diferentes
    assert validate_legs(Structure.COVERED_CALL, [call]) is None
    assert validate_legs(Structure.COVERED_CALL, [put]) is not None


def test_simulation_is_deterministic_by_seed() -> None:
    m = Market(S0, R_C, T_BD)
    z = rescale_returns(_gaussian_sample(), 0.25)
    rule = HedgeRule(True, 0.1, 0.0005)
    a = simulate_paths(_straddle(-1), 0, m, rule, z, paths=500, seed=11)
    b = simulate_paths(_straddle(-1), 0, m, rule, z, paths=500, seed=11)
    c = simulate_paths(_straddle(-1), 0, m, rule, z, paths=500, seed=12)
    assert np.array_equal(a.pnl, b.pnl)
    assert not np.array_equal(a.pnl, c.pnl)


def test_covered_call_has_no_rehedges() -> None:
    t = T_BD / 252
    call = Leg(True, 42.0, -1, IV, float(bs_price(S0, 42.0, t, R_C, IV, True)), 0.0)
    m = Market(S0, R_C, T_BD)
    res = simulate_paths(
        [call], 1, m, HedgeRule(False, 0.1, 0.0), rescale_returns(_gaussian_sample(), 0.25), paths=300, seed=3
    )
    assert int(res.rehedges.sum()) == 0
    # Sem custos e sem juros: P&L = prêmio + (S_T − S0) − (S_T − K)⁺, caminho a caminho (≤ prêmio + K − S0).
    assert float(res.pnl.max()) <= call.price + 42.0 - S0 + 1e-9


def test_hedged_straddle_mean_pnl_matches_price_difference() -> None:
    """Sem custos e com banda estreita, vendido a IV e realizada σ̂: E[P&L] ≈ Σ (BS(IV) − BS(σ̂))."""
    sigma = 0.20
    m = Market(S0, R_C, T_BD)
    z = rescale_returns(_gaussian_sample(20_000), sigma)
    res = simulate_paths(_straddle(-1), 0, m, HedgeRule(True, 0.01, 0.0), z, paths=10_000, seed=5)
    t = T_BD / 252
    expected = sum(
        float(bs_price(S0, S0, t, R_C, IV, c) - bs_price(S0, S0, t, R_C, sigma, c)) for c in (True, False)
    )
    se = float(res.pnl.std()) / math.sqrt(res.pnl.size)
    # Tolerância documentada: 4 erros-padrão + 5% (hedge discreto diário e banda de 0,01).
    assert abs(float(res.pnl.mean()) - expected) < 4 * se + 0.05 * expected


def test_tighter_band_reduces_dispersion_and_matches_eq_7_7_order() -> None:
    sigma = 0.30
    m = Market(S0, R_C, T_BD)
    z = rescale_returns(_gaussian_sample(20_000), sigma)
    legs = _straddle(-1)
    tight = simulate_paths(legs, 0, m, HedgeRule(True, 0.0, 0.0), z, paths=4000, seed=9)
    wide = simulate_paths(legs, 0, m, HedgeRule(True, 0.3, 0.0), z, paths=4000, seed=9)
    assert tight.pnl.std() < wide.pnl.std()
    # Eq. 7.7 (Kamal-Derman) com hedge diário: mesma ordem de grandeza (fator 2).
    vega = structure_greeks(legs, 0, m).vega_per_point
    kd = kamal_derman_std(vega, sigma, T_BD)
    assert kd is not None
    assert 0.5 < float(tight.pnl.std()) / kd < 2.0


def test_costs_reduce_mean_pnl_and_are_tracked() -> None:
    m = Market(S0, R_C, T_BD)
    z = rescale_returns(_gaussian_sample(), 0.25)
    free = simulate_paths(_straddle(-1), 0, m, HedgeRule(True, 0.1, 0.0), z, paths=2000, seed=4)
    paid = simulate_paths(_straddle(-1, cost=0.01), 0, m, HedgeRule(True, 0.1, 0.001), z, paths=2000, seed=4)
    assert paid.entry_cost == pytest.approx(0.01 * sum(leg.price for leg in _straddle(-1)), rel=1e-12)
    assert float(paid.hedge_cost.min()) > 0
    assert np.allclose(free.pnl - paid.pnl, paid.entry_cost + paid.hedge_cost, rtol=0, atol=1e-9)


def test_summarize_per_lot() -> None:
    m = Market(S0, R_C, T_BD)
    res = simulate_paths(
        _straddle(-1),
        0,
        m,
        HedgeRule(True, 0.1, 0.0),
        rescale_returns(_gaussian_sample(), 0.25),
        paths=1000,
        seed=2,
    )
    d = summarize(res, lot_size=100, es_level=0.99, bins=20)
    assert d.mean == pytest.approx(100 * float(res.pnl.mean()), rel=1e-12)
    assert d.variance == pytest.approx(100**2 * float(res.pnl.var()), rel=1e-12)
    assert sum(d.hist_counts) == 1000 and len(d.hist_edges) == 21
    assert d.percentiles[1] <= d.percentiles[50] <= d.percentiles[99]
    assert d.es >= -d.percentiles[1] - 1e-9


# --- Payoff, Greeks e IV da estrutura (RF-SIM-02) ----------------------------------------------


def test_payoff_at_expiry_is_intrinsic_minus_premium() -> None:
    legs = _straddle(-1)
    premium = sum(leg.price for leg in legs)
    m = Market(S0, R_C, T_BD)
    spots = np.array([30.0, 40.0, 50.0])
    got = payoff_curve(legs, 0, m, spots, T_BD)
    assert got == pytest.approx([premium - 10.0, premium, premium - 10.0], abs=1e-12)
    assert payoff_curve(legs, 0, m, np.array([S0]), 0)[0] == pytest.approx(0.0, abs=1e-12)


def test_structure_greeks_and_iv() -> None:
    legs = _straddle(1)
    m = Market(S0, R_C, T_BD)
    g = structure_greeks(legs, 0, m)
    ref = bs_greeks(S0, np.array([S0, S0]), T_BD / 252, R_C, IV, np.array([True, False]))
    assert g.vega_per_point == pytest.approx(float(ref.vega_per_point.sum()), rel=1e-14)
    assert g.delta == pytest.approx(float(ref.delta.sum()), rel=1e-14)
    assert structure_iv(legs, m) == pytest.approx(IV, rel=1e-14)
    mixed = [legs[0], Leg(False, S0, 1, 0.40, legs[1].price, 0.0)]
    assert IV < structure_iv(mixed, m) < 0.40


def test_dividend_lowers_path_and_pays_stock() -> None:
    """Provento na vida: o caminho cai D na data ex e a ação em carteira recebe D (venda coberta)."""
    t = T_BD / 252
    m0 = Market(S0, R_C, T_BD)
    m1 = Market(S0, R_C, T_BD, ((10, 1.0),))
    k_eff = 45.0
    pv = m1.pv_dividends(0)
    call1 = Leg(True, k_eff, -1, IV, float(bs_price(S0, k_eff, t, R_C, IV, True, pv)), 0.0)
    call0 = Leg(True, k_eff, -1, IV, float(bs_price(S0, k_eff, t, R_C, IV, True)), 0.0)
    z = np.zeros(10)  # caminho determinístico (σ̂_d² = 0): só o provento move o preço
    rule = HedgeRule(False, 0.0, 0.0)
    r0 = simulate_paths([call0], 1, m0, rule, z, paths=1, seed=1)
    r1 = simulate_paths([call1], 1, m1, rule, z, paths=1, seed=1)
    # Sem provento: P&L = prêmio. Com provento: prêmio (menor) + D − D (queda do preço) = prêmio.
    assert float(r0.pnl[0]) == pytest.approx(call0.price, abs=1e-12)
    assert float(r1.pnl[0]) == pytest.approx(call1.price, abs=1e-12)


# --- Stress na entrada (QA-09) ------------------------------------------------------------------


def test_stress_losses_by_hand() -> None:
    legs = _straddle(-1)
    m = Market(S0, R_C, T_BD)
    rule = HedgeRule(True, 0.1, 0.0)
    n0 = initial_hedge(legs, 0, m, True)
    scen = [StressScenario("queda", -0.10, 0.0), StressScenario("vol", 0.0, 0.10)]
    out = stress_losses(legs, 0, m, rule, scen, exit_cost_rates=[0.0, 0.0])
    t = T_BD / 252
    s1 = S0 * 0.9
    by_hand = -(
        n0 * (s1 - S0)
        - sum(
            float(bs_price(s1, S0, t, R_C, IV, c)) - leg.price
            for c, leg in zip((True, False), legs, strict=True)
        )
    )
    assert out[0].loss == pytest.approx(by_hand, abs=1e-12)
    vol_hand = sum(
        float(bs_price(S0, S0, t, R_C, IV + 0.10, c)) - leg.price
        for c, leg in zip((True, False), legs, strict=True)
    )
    assert out[1].loss == pytest.approx(vol_hand, abs=1e-12)
    assert out[1].loss > 0  # vendido em vol perde com alta de vol
    with_costs = stress_losses(legs, 0, m, HedgeRule(True, 0.1, 0.001), scen, exit_cost_rates=[0.01, 0.01])
    assert all(c.loss > b.loss for c, b in zip(with_costs, out, strict=True))


def test_units_are_decimal() -> None:
    """T-REF-06 aplicado à Etapa 6: vol, banda e choques em decimal; nada em %."""
    z = rescale_returns(_gaussian_sample(), 0.25)
    assert float(np.std(z)) < 0.05  # retorno diário em decimal
    assert StressScenario("vol", 0.0, 0.10).vol_shock < 1.0
