"""Regras de gestão da operação nos limites (PRD 1.11 §5.10 e §10.2; BRD 1.8 RN-GES-01..07, RS-07).

Critério de saída da Etapa 8 no PLANO: "testes de cada regra nos limites". Puro, sem banco.
"""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vollab.analytics.management import nth_business_day_after
from vollab.analytics.params import ManagementParams
from vollab.quant.edge import Direction, Premium
from vollab.quant.management import (
    OpenAlert,
    RuleState,
    exit_dte,
    exit_edge,
    exit_profit,
    exit_stop,
    hedge_band,
    hedge_time,
    in_dividend_window,
    position_edge,
    reconcile,
    roll_expiry,
    shares_to_band,
)

T = RuleState.TRIGGERED
OK = RuleState.OK


def test_defaults_follow_user_decisions() -> None:
    """QA-11 (2026-11-24): tempo, meta e stop desligados; prazo 5 du; rolagem ≥ 10 du; proventos 5 du."""
    mg = ManagementParams()
    assert mg.hedge_interval_bd is None
    assert mg.profit_target_fraction is None and mg.stop_loss_fraction is None
    assert (mg.exit_dte_bd, mg.roll_min_dte_bd, mg.dividend_lead_bd) == (5, 10, 5)


# --- Hedge (RN-GES-01) -----------------------------------------------------------------------------


def test_hedge_band_strict_at_border() -> None:
    half = 10.0  # 0,10 × lote 100 × 1 lote
    assert hedge_band(10.0, half).state is OK
    assert hedge_band(-10.0, half).state is OK
    assert hedge_band(10.0 + 1e-9, half).state is T
    assert hedge_band(-10.000001, half).state is T
    assert hedge_band(None, half).state is RuleState.UNAVAILABLE


@pytest.mark.parametrize(
    ("delta", "expected"),
    [(25.0, -15), (-25.0, 15), (10.5, -1), (-10.2, 1), (10.0, 0), (0.0, 0), (17.0, -7)],
)
def test_adjustment_goes_to_the_border(delta: float, expected: int) -> None:
    """H1: ajustar só até a borda; arredondado para cima em módulo (fica na borda ou dentro)."""
    assert shares_to_band(delta, 10.0) == expected
    after = delta + expected
    assert abs(after) <= 10.0 + 1e-9


@given(st.floats(-1e5, 1e5), st.floats(1, 1e4))
def test_adjustment_never_overshoots(delta: float, half: float) -> None:
    """Meia-largura ≥ 1 ação (na prática 0,10 × 100 × lotes ≥ 10): ações inteiras cabem na banda."""
    adj = shares_to_band(delta, half)
    after = delta + adj
    assert abs(after) <= half + 1e-6 or adj == 0
    if abs(delta) > half:
        assert abs(after) > half - 1.0 - 1e-6  # não passa da borda por mais de uma ação


def test_hedge_time_disabled_by_default_and_limits() -> None:
    assert hedge_time(30, None, 50.0).state is RuleState.DISABLED
    assert hedge_time(5, 5, 50.0).state is T
    assert hedge_time(4, 5, 50.0).state is OK
    assert hedge_time(9, 5, 0.0).state is OK  # delta zero: nada a ajustar
    assert hedge_time(None, 5, None).state is RuleState.UNAVAILABLE


# --- Saída (RN-GES-02/03) --------------------------------------------------------------------------


def _p(value: float, lo: float, hi: float) -> Premium:
    return Premium(value, lo, hi)


def test_position_edge_by_hand_short() -> None:
    """Venda: (p − c)/σ̂ com c = manter + fechar; intervalo herdado de p."""
    e = position_edge(
        _p(0.04, 0.02, 0.06), sigma=0.25, direction=Direction.SELL, cost_hold=0.01, cost_close=0.005
    )
    assert e.value == pytest.approx((0.04 - 0.015) / 0.25)
    assert e.ci_low == pytest.approx((0.02 - 0.015) / 0.25)
    assert e.ci_high == pytest.approx((0.06 - 0.015) / 0.25)


def test_position_edge_by_hand_long() -> None:
    """Compra: (−p − c)/σ̂; o limite inferior vem de p_hi."""
    e = position_edge(
        _p(-0.05, -0.07, -0.03), sigma=0.30, direction=Direction.BUY, cost_hold=0.012, cost_close=0.003
    )
    assert e.value == pytest.approx((0.05 - 0.015) / 0.30)
    assert e.ci_low == pytest.approx((0.03 - 0.015) / 0.30)
    assert e.ci_high == pytest.approx((0.07 - 0.015) / 0.30)


def test_exit_edge_point_estimate_at_zero_fires() -> None:
    """RN-GES-02: dispara com o edge pontual ≤ 0 ("não é mais positivo"); levemente positivo não."""
    zero = position_edge(
        _p(0.02, 0.0, 0.04), sigma=0.2, direction=Direction.SELL, cost_hold=0.015, cost_close=0.005
    )
    assert zero.value == pytest.approx(0.0)
    assert exit_edge(zero).state is T
    pos = position_edge(
        _p(0.0201, 0.0, 0.04), sigma=0.2, direction=Direction.SELL, cost_hold=0.015, cost_close=0.005
    )
    assert pos.value is not None and pos.value > 0
    assert exit_edge(pos).state is OK  # mesmo com o limite inferior negativo
    assert exit_edge(None, "sem previsão").state is RuleState.UNAVAILABLE


def test_exit_edge_long_when_hedge_consumes_everything() -> None:
    e = position_edge(
        _p(-0.05, -0.07, -0.03), sigma=0.3, direction=Direction.BUY, cost_hold=None, cost_close=0.0
    )
    r = exit_edge(e)
    assert r.state is T and r.reason is not None


def test_exit_dte_limits() -> None:
    assert exit_dte(5, 5).state is T
    assert exit_dte(6, 5).state is OK
    assert exit_dte(0, 5).state is T
    assert exit_dte(3, None).state is RuleState.DISABLED
    assert exit_dte(None, 5).state is RuleState.UNAVAILABLE


def test_profit_and_stop_disabled_by_default_and_limits() -> None:
    mg = ManagementParams()
    assert exit_profit(1e6, 100.0, mg.profit_target_fraction).state is RuleState.DISABLED
    assert exit_stop(-1e6, 100.0, mg.stop_loss_fraction).state is RuleState.DISABLED
    # Meta: P&L ≥ f × esperado.
    assert exit_profit(100.0, 100.0, 1.0).state is T
    assert exit_profit(99.99, 100.0, 1.0).state is OK
    assert exit_profit(50.0, 100.0, 0.5).state is T
    assert exit_profit(10.0, 0.0, 1.0).state is RuleState.UNAVAILABLE  # esperado ≤ 0
    assert exit_profit(10.0, -5.0, 1.0).state is RuleState.UNAVAILABLE
    # Stop: P&L ≤ −f × perda máxima.
    assert exit_stop(-300.0, 300.0, 1.0).state is T
    assert exit_stop(-299.99, 300.0, 1.0).state is OK
    assert exit_stop(-150.0, 300.0, 0.5).state is T
    assert exit_stop(-1.0, None, 1.0).state is RuleState.UNAVAILABLE


# --- Rolagem (RN-GES-04) ---------------------------------------------------------------------------


def test_roll_expiry_first_with_min_days() -> None:
    dtes = {date(2026, 12, 18): 18, date(2027, 1, 15): 36, date(2026, 11, 27): 6}
    assert roll_expiry(dtes, dtes.__getitem__, 10) == date(2026, 12, 18)
    assert roll_expiry(dtes, dtes.__getitem__, 18) == date(2026, 12, 18)
    assert roll_expiry(dtes, dtes.__getitem__, 19) == date(2027, 1, 15)
    assert roll_expiry(dtes, dtes.__getitem__, 40) is None


# --- Proventos (RN-GES-06) -------------------------------------------------------------------------


def test_dividend_window_borders() -> None:
    """Data ex em (t, t + 5 du]: em t + 5 du dispara, em t + 6 du não, em t não."""
    t = date(2026, 11, 19)  # quinta-feira; 20/11 é feriado (Consciência Negra)
    holidays = {date(2026, 11, 20)}
    end = nth_business_day_after(t, 5, holidays)
    assert end == date(2026, 11, 27)  # 23, 24, 25, 26, 27
    assert in_dividend_window(end, t, end)
    assert not in_dividend_window(nth_business_day_after(t, 6, holidays), t, end)
    assert not in_dividend_window(t, t, end)
    assert in_dividend_window(date(2026, 11, 23), t, end)


# --- Ciclo de vida (RN-GES-07) ---------------------------------------------------------------------

A = ("hedge_band", 1, "")
B = ("exit_dte", 1, "")
C = ("limit_vega", None, "")


def test_reconcile_create_update_resolve() -> None:
    plan = reconcile([OpenAlert(10, A), OpenAlert(11, B)], [A, C], [], lambda k: True)
    assert plan.create == [C]  # nova condição
    assert plan.update == [(10, A)]  # continua: atualiza sem mudar o estado
    assert plan.resolve == [11]  # sumiu: resolve sozinho
    assert plan.release == []


def test_reconcile_dedup_and_no_data() -> None:
    """Uma chave nunca abre dois alertas; posição sem avaliação não resolve por falta de dado."""
    plan = reconcile([OpenAlert(10, A)], [A, A], [], lambda k: k[1] is None)
    assert plan.create == [] and plan.update == [(10, A)]
    plan = reconcile([OpenAlert(11, B)], [], [], lambda k: k[1] is None)
    assert plan.resolve == []


def test_reconcile_user_resolution_holds_until_condition_clears() -> None:
    held = [A]
    # Condição continua: não reabre.
    plan = reconcile([], [A], held, lambda k: True)
    assert plan.create == [] and plan.release == []
    # Condição some: libera a chave.
    plan = reconcile([], [], held, lambda k: True)
    assert plan.release == [A]
    # Depois de liberada, voltar a valer abre um alerta novo.
    plan = reconcile([], [A], [], lambda k: True)
    assert plan.create == [A]


def test_management_params_validation() -> None:
    with pytest.raises(ValueError):
        ManagementParams(exit_dte_bd=-1)
    with pytest.raises(ValueError):
        ManagementParams(stop_loss_fraction=0)
    with pytest.raises(ValueError):
        ManagementParams(roll_min_dte_bd=0)
    assert ManagementParams(exit_dte_bd=None).exit_dte_bd is None
