"""Etapa 7 (PRD 1.10 §5.9 e §10.2): validações RS-06 do diário, estorno, exercício e designação,
status e vencimento pendente; stress por reprecificação × cálculo à mão; limites nos três estados e
nas fronteiras (comparação estrita); medição da crise (pior janela, IV ATM dos fechamentos, RV).
Unidades: nada em %.
"""

import math
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from vollab.quant.crisis import OptionClose, atm_iv, rv_zero_mean, worst_day, worst_window
from vollab.quant.journal import (
    EntryKind,
    LedgerEntry,
    LedgerError,
    OptionInfo,
    PositionBook,
    holdings_until,
    pending_expiry,
    replay,
    validate_new,
)
from vollab.quant.pricing import bs_price
from vollab.quant.risk import (
    Book,
    LimitsConfig,
    LimitState,
    RiskLeg,
    RiskStock,
    Scenario,
    Shock,
    evaluate_limits,
    exposures,
    run_scenario,
    standard_scenarios,
)

pytestmark = pytest.mark.reference

STOCK = "PETR4"
CALL, PUT = "PETRL44", "PETRX44"
EXPIRY = date(2026, 12, 18)
NOW = datetime(2026, 12, 30, 12, 0, tzinfo=UTC)
Z = Decimal(0)


def _at(d: date, hour: int = 15) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=UTC)


def _book(european: bool = True) -> PositionBook:
    return PositionBook(
        STOCK,
        {
            CALL: OptionInfo(CALL, 1, True, EXPIRY, european),
            PUT: OptionInfo(PUT, 2, False, EXPIRY, european),
        },
    )


def _entries(long: bool = False) -> list[LedgerEntry]:
    q = 100 if long else -100
    d = date(2026, 11, 19)
    return [
        LedgerEntry(1, EntryKind.ENTRY, CALL, q, Decimal("1.50"), Z, Z, _at(d), 1),
        LedgerEntry(2, EntryKind.ENTRY, PUT, q, Decimal("1.40"), Z, Z, _at(d), 2),
    ]


def _e(
    id_: int,
    kind: EntryKind,
    inst: str,
    q: int,
    price: str = "1",
    day: date = date(2026, 11, 24),
    **kw: object,
) -> LedgerEntry:
    return LedgerEntry(id_, kind, inst, q, Decimal(price), Z, Z, _at(day), **kw)  # type: ignore[arg-type]


def _reject(
    existing: list[LedgerEntry], new: LedgerEntry, match: str, book: PositionBook | None = None
) -> None:
    with pytest.raises(LedgerError, match=match):
        validate_new(existing, new, book or _book(), now=NOW)


# --- RS-06 ---------------------------------------------------------------------------------------


def test_hedge_and_exit_update_holdings() -> None:
    es = _entries()
    led = validate_new(es, _e(3, EntryKind.HEDGE, STOCK, 30, "36.5"), _book(), now=NOW)
    assert led.holdings == {CALL: -100, PUT: -100, STOCK: 30}
    led = validate_new(
        [*es, _e(3, EntryKind.HEDGE, STOCK, 30)], _e(4, EntryKind.EXIT, PUT, 40), _book(), now=NOW
    )
    assert led.holdings[PUT] == -60 and led.is_open


def test_exit_cannot_flip_sign_or_exceed() -> None:
    es = _entries()
    _reject(es, _e(3, EntryKind.EXIT, PUT, 101), "direção a zero")
    _reject(es, _e(3, EntryKind.EXIT, PUT, -10), "direção a zero")
    _reject(es, _e(3, EntryKind.EXIT, STOCK, 10), "sem quantidade")


def test_instrument_must_belong_to_position() -> None:
    _reject(_entries(), _e(3, EntryKind.EXIT, "VALE3", 10), "não pertence")
    _reject(_entries(), _e(3, EntryKind.HEDGE, CALL, 10), "Hedge só com a ação")


def test_date_rules() -> None:
    _reject(_entries(), _e(3, EntryKind.HEDGE, STOCK, 10, day=date(2026, 11, 18)), "anterior à entrada")
    _reject(_entries(), _e(3, EntryKind.HEDGE, STOCK, 10, day=date(2027, 1, 5)), "futuro")


def test_exercise_only_long_and_assignment_only_short() -> None:
    _reject(_entries(long=False), _e(3, EntryKind.EXERCISE, CALL, 100, "34", EXPIRY), "perna comprada")
    _reject(_entries(long=True), _e(3, EntryKind.ASSIGNMENT, CALL, -100, "34", EXPIRY), "perna vendida")


def test_european_only_on_expiry_american_until_expiry() -> None:
    _reject(_entries(long=True), _e(3, EntryKind.EXERCISE, CALL, -100, "34", date(2026, 12, 10)), "europeia")
    led = validate_new(
        _entries(long=True),
        _e(3, EntryKind.EXERCISE, CALL, -100, "34", date(2026, 12, 10)),
        _book(False),
        now=NOW,
    )
    assert led.holdings[CALL] == 0
    _reject(
        _entries(long=True),
        _e(3, EntryKind.EXERCISE, CALL, -100, "34", date(2026, 12, 21)),
        "depois do vencimento",
        _book(False),
    )


def test_exercise_and_assignment_move_stock_at_strike() -> None:
    led = validate_new(
        _entries(long=True), _e(3, EntryKind.EXERCISE, PUT, -100, "34", EXPIRY), _book(), now=NOW
    )
    assert led.holdings[STOCK] == -100 and led.holdings[PUT] == 0
    led = validate_new(_entries(), _e(3, EntryKind.ASSIGNMENT, CALL, 100, "34", EXPIRY), _book(), now=NOW)
    assert led.holdings[STOCK] == -100 and led.holdings[CALL] == 0
    led = validate_new(_entries(), _e(3, EntryKind.ASSIGNMENT, PUT, 100, "34", EXPIRY), _book(), now=NOW)
    assert led.holdings[STOCK] == 100
    stock_tx = [t for t in led.transactions if t.instrument == STOCK]
    assert stock_tx[0].price == Decimal(34)


def test_exercise_at_intrinsic_sums_only_costs() -> None:
    """No vencimento, a opção marcada pelo intrínseco sai a 0 e a ação entra ao strike: a linha de
    execução e custos soma só os custos."""
    from vollab.quant.attribution import DayMark, LegMark, execution_line

    entry = LedgerEntry(
        3, EntryKind.EXERCISE, CALL, -100, Decimal(34), Decimal("2.5"), Decimal(1), _at(EXPIRY)
    )
    led = validate_new(_entries(long=True), entry, _book(), now=NOW)
    spot = Decimal("37.20")
    legs = {CALL: LegMark(CALL, 0, spot - 34, None, "expired", 0, 0, 0, 0)}
    mark = DayMark(EXPIRY, spot, 100, legs)
    txs = [t for t in led.transactions if t.entry_id == 3]
    assert execution_line(mark, txs, stock_code=STOCK) == Decimal("-3.5")


def test_void_restores_and_rules() -> None:
    es = [*_entries(), _e(3, EntryKind.HEDGE, STOCK, 30)]
    led = validate_new(es, _e(4, EntryKind.VOID, STOCK, 30, linked_entry_id=3), _book(), now=NOW)
    assert led.holdings.get(STOCK, 0) == 0
    _reject(es, _e(4, EntryKind.VOID, CALL, -100, linked_entry_id=1), "entrada não se estorna")
    voided = [*es, _e(4, EntryKind.VOID, STOCK, 30, linked_entry_id=3)]
    _reject(voided, _e(5, EntryKind.VOID, STOCK, 30, linked_entry_id=3), "já foi estornado")
    _reject(voided, _e(5, EntryKind.VOID, STOCK, 30, linked_entry_id=4), "estorno não se estorna")
    _reject(es, _e(5, EntryKind.VOID, STOCK, 30, linked_entry_id=99), "não é desta operação")


def test_void_cannot_break_later_entries() -> None:
    es = [
        *_entries(),
        _e(3, EntryKind.HEDGE, STOCK, 30),
        _e(4, EntryKind.EXIT, STOCK, -30, day=date(2026, 11, 25)),
    ]
    _reject(es, _e(5, EntryKind.VOID, STOCK, 30, linked_entry_id=3), "posteriores inconsistentes")


def test_backdated_entry_cannot_break_later_ones() -> None:
    es = [*_entries(), _e(3, EntryKind.EXIT, PUT, 100, day=date(2026, 11, 25))]
    # A saída de 60 em 24/11 deixaria a de 100 em 25/11 acima do aberto.
    _reject(es, _e(4, EntryKind.EXIT, PUT, 60, day=date(2026, 11, 24)), "direção a zero")


def test_closed_position_accepts_only_void() -> None:
    es = [*_entries(), _e(3, EntryKind.EXIT, CALL, 100), _e(4, EntryKind.EXIT, PUT, 100)]
    assert not replay(es, _book()).is_open
    _reject(es, _e(5, EntryKind.HEDGE, STOCK, 10), "encerrada")
    led = validate_new(es, _e(5, EntryKind.VOID, PUT, 100, linked_entry_id=4), _book(), now=NOW)
    assert led.is_open


def test_strike_adjustment_rules() -> None:
    _reject(_entries(), _e(3, EntryKind.STRIKE_ADJUSTMENT, CALL, 110), "mesmo sinal")
    _reject(_entries(), _e(3, EntryKind.STRIKE_ADJUSTMENT, CALL, -110), "strike_after")
    led = validate_new(
        _entries(),
        _e(3, EntryKind.STRIKE_ADJUSTMENT, CALL, -110, "0", strike_after=Decimal("33.2")),
        _book(),
        now=NOW,
    )
    assert led.holdings[CALL] == -110 and led.strikes_after[CALL] == Decimal("33.2")


def test_pending_expiry_and_holdings_until() -> None:
    led = replay([*_entries(), _e(3, EntryKind.EXIT, CALL, 100, "0", EXPIRY)], _book())
    assert pending_expiry(led, _book(), date(2026, 12, 21)) == [PUT]
    assert pending_expiry(led, _book(), EXPIRY) == []
    assert holdings_until(led, date(2026, 11, 20)) == {CALL: -100, PUT: -100}


# --- Stress e limites ----------------------------------------------------------------------------


def _risk_book() -> Book:
    legs = [
        RiskLeg(1, STOCK, EXPIRY, CALL, -100, True, 36.0, 20, 0.32, 0.14, 0.0),
        RiskLeg(1, STOCK, EXPIRY, PUT, -100, False, 36.0, 20, 0.33, 0.14, 0.0),
    ]
    return Book(legs, [RiskStock(1, STOCK, EXPIRY, 12)], {STOCK: 36.4})


def test_stress_by_full_repricing_matches_hand() -> None:
    book = _risk_book()
    sc = Scenario("down_vol_up", {STOCK: Shock(-0.10, 0.10)})
    r = run_scenario(book, sc)
    t = 20 / 252
    hand = 12 * 36.4 * -0.10
    for strike, iv, call in ((36.0, 0.32, True), (36.0, 0.33, False)):
        v0 = float(bs_price(36.4, strike, t, 0.14, iv, call))
        v1 = float(bs_price(36.4 * 0.9, strike, t, 0.14, iv + 0.10, call))
        hand += -100 * (v1 - v0)
    assert math.isclose(r.pnl_total, hand, rel_tol=1e-12)
    assert r.pnl_by_position[1] == pytest.approx(hand)


def test_stress_iv_floor_and_missing_ticker() -> None:
    book = _risk_book()
    r = run_scenario(book, Scenario("vol_crash", {STOCK: Shock(0.0, -0.50)}))
    t = 20 / 252
    hand = sum(
        -100 * (float(bs_price(36.4, 36.0, t, 0.14, 0.01, c)) - float(bs_price(36.4, 36.0, t, 0.14, iv, c)))
        for iv, c in ((0.32, True), (0.33, False))
    )
    assert r.pnl_total == pytest.approx(hand)
    assert run_scenario(book, Scenario("x", {})).missing_tickers == (STOCK,)


def test_exposures_by_key() -> None:
    e = exposures(_risk_book(), "total")["total"]
    assert e.delta_brl == pytest.approx(e.delta_shares * 36.4)
    assert e.vega_per_point_brl < 0 and e.theta_per_bd_brl > 0 and e.gamma < 0
    assert set(exposures(_risk_book(), "expiry")) == {(STOCK, EXPIRY)}


CFG = LimitsConfig(0.20, 0.01, 0.50, 0.60)


def test_limits_three_states_and_strict_boundary() -> None:
    book = _risk_book()
    results = [run_scenario(book, s) for s in standard_scenarios([STOCK], 0.10, 0.10)]
    worst = max(r.loss for r in results)
    # Capital em que a perda é exatamente 20%: ok (igual não estoura); um pouco menos: estoura.
    at_limit = evaluate_limits(results, 0.0, worst / 0.20, CFG)
    assert at_limit[0].state is LimitState.OK and at_limit[0].usage == pytest.approx(1.0)
    below = evaluate_limits(results, 0.0, worst / 0.20 * 0.999, CFG)
    assert below[0].state is LimitState.BREACHED
    none = evaluate_limits(results, 0.0, None, CFG)
    assert {x.state for x in none} == {LimitState.UNAVAILABLE}
    # Concentração pelo orçamento de perda: ativo único com perda = 50% do orçamento → ok.
    conc = evaluate_limits(results, 0.0, worst / (0.20 * 0.50), CFG)
    und = next(x for x in conc if x.name == "underlying_concentration")
    assert und.value == pytest.approx(0.50) and und.state is LimitState.OK
    vega = evaluate_limits(results, -1000.0, 100_000.0, CFG)
    assert next(x for x in vega if x.name == "vega_total").state is LimitState.OK
    vega = evaluate_limits(results, -1000.01, 100_000.0, CFG)
    assert next(x for x in vega if x.name == "vega_total").state is LimitState.BREACHED


# --- Crise (QA-12) -------------------------------------------------------------------------------


def test_worst_window_and_day() -> None:
    r = [0.01, -0.02, -0.05, 0.01, -0.03, float("nan"), -0.10, 0.02]
    w = worst_window(r, 0, 7, 3)
    assert w is not None and (w.start, w.end) == (2, 4) and w.log_return == pytest.approx(-0.07)
    assert w.simple_return == pytest.approx(math.expm1(-0.07))
    assert worst_day(r, 0, 7) == (6, -0.10)
    assert worst_window(r, 0, 1, 3) is None


def test_rv_zero_mean() -> None:
    r = [0.01] * 25
    assert rv_zero_mean(r, 24) == pytest.approx(0.01 * math.sqrt(252))
    assert rv_zero_mean(r, 10) is None


def test_atm_iv_from_closes_round_trip() -> None:
    t = 21 / 252
    c = float(bs_price(25.0, 25.0, t, 0.10, 0.45, True))
    p = float(bs_price(25.0, 25.0, t, 0.10, 0.45, False))
    opts = [
        OptionClose(True, 25.0, 21, c, 50),
        OptionClose(False, 25.0, 21, p, 50),
        OptionClose(True, 26.0, 21, 0.5, 50),  # sem put no strike: ignorada
        OptionClose(True, 25.0, 5, 0.3, 500),  # vencimento curto demais
        OptionClose(False, 25.0, 5, 0.3, 500),
    ]
    assert atm_iv(25.0, opts, 0.10) == pytest.approx(0.45, abs=1e-8)
    illiquid = [OptionClose(True, 25.0, 21, c, 19), OptionClose(False, 25.0, 21, p, 50)]
    assert atm_iv(25.0, illiquid, 0.10) is None


# --- Validação de entrada (revisão de segurança da Etapa 7) --------------------------------------


def test_crisis_episode_and_override_validation() -> None:
    from pydantic import ValidationError

    from vollab.analytics.params import CrisisEpisode, RiskParams

    with pytest.raises(ValidationError, match="2000"):
        CrisisEpisode(key="velho", label="velho", start=date(1999, 12, 1), end=date(2000, 1, 31))
    with pytest.raises(ValidationError, match="ano anterior"):
        CrisisEpisode(key="hoje", label="hoje", start=date(2099, 1, 1), end=date(2099, 2, 1))
    with pytest.raises(ValidationError, match="Ticker"):
        RiskParams(crisis_overrides={"ÁBÇD": {"mar2020": {"price_shock": -0.1, "vol_shock": 0.1}}})


def test_entry_text_is_stripped_and_control_chars_refused() -> None:
    from pydantic import ValidationError

    from vollab.api.schemas.journal import EntryCreate

    at = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match=r"10"):
        EntryCreate(kind="void", executed_at=at, linked_entry_id=1, void_reason=" " * 12)
    with pytest.raises(ValidationError, match="controle"):
        EntryCreate(kind="void", executed_at=at, linked_entry_id=1, void_reason="motivo\x00 válido aqui")
    ok = EntryCreate(kind="void", executed_at=at, linked_entry_id=1, void_reason="  hedge em dobro  ")
    assert ok.void_reason == "hedge em dobro"
