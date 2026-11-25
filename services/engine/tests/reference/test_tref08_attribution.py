"""T-REF-08 (PRD 1.10 §10.2): atribuição de P&L em série sintética gerada pelo próprio modelo.

Caminhos de MBG com IV constante e com IV em passeio aleatório pequeno, marcados pelo próprio BS: a
razão do CS-04 (Σ|resíduo| ÷ Σ|delta|+|gamma|+|theta|+|vega|) fica abaixo de 0,15 no passo diário e
diminui quando o passo diminui. Ordem esperada: o resíduo por passo é O(dS³) ~ dt^1,5 e as
contribuições são O(dt), então a razão cai como ~dt^0,5 (passo 4× menor → razão ~2× menor; o teste
exige pelo menos 25% de queda na média de 20 caminhos). Com S e IV fixos só há theta e o resíduo é
de segunda ordem no tempo. O invariante mercado + execução = P&L pelos fluxos de caixa é exato em
`Decimal`.
"""

import itertools
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from vollab.quant.attribution import (
    DayMark,
    LegQuote,
    attribute_life,
    cs04_ratio,
    error_flag,
    mark_legs,
)
from vollab.quant.journal import EntryKind, LedgerEntry, OptionInfo, PositionBook, replay

pytestmark = pytest.mark.reference

STOCK = "SYNT3"
CALL, PUT = "SYNTA100", "SYNTM100"
RATE_C = 0.10
K = 100.0
T0_BD = 60.0


def _marks(
    spots: np.ndarray, ivs: np.ndarray, step_bd: float, quantities: dict[str, int], stock_qty: int
) -> list[DayMark]:
    out = []
    base = date(2026, 1, 1)
    for i, (s, iv) in enumerate(zip(spots, ivs, strict=True)):
        days = T0_BD - i * step_bd
        quotes = [
            LegQuote(CALL, True, K, days, float(iv), "observed"),
            LegQuote(PUT, False, K, days, float(iv), "observed"),
        ]
        legs = mark_legs(float(s), RATE_C, 0.0, quotes, quantities)
        out.append(DayMark(base + timedelta(days=i), Decimal(repr(float(s))), stock_qty, legs))
    return out


def _path(seed: int, step_bd: float, n_steps: int, sigma: float, iv_noise: float) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    dt = step_bd / 252.0
    z = rng.standard_normal(n_steps)
    log_s = np.concatenate([[0.0], np.cumsum((RATE_C - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z)])
    spots = 100.0 * np.exp(log_s)
    w = rng.standard_normal(n_steps) * iv_noise * np.sqrt(step_bd)
    ivs = np.concatenate([[sigma], sigma + np.cumsum(w)])
    return spots, np.maximum(ivs, 0.05)


def _ratio(seed: int, step_bd: float, horizon_bd: float, iv_noise: float) -> float:
    n = round(horizon_bd / step_bd)
    spots, ivs = _path(seed, step_bd, n, 0.30, iv_noise)
    q = {CALL: -100, PUT: -100}
    marks = _marks(spots, ivs, step_bd, q, 0)
    days = attribute_life(marks, [], stock_code=STOCK, dividends={}, days_between=lambda a, b: step_bd)
    ratio = cs04_ratio(days)
    assert ratio is not None
    return ratio


@pytest.mark.parametrize("iv_noise", [0.0, 0.003])
def test_tref08_residual_below_cs04_daily(iv_noise: float) -> None:
    ratios = [_ratio(seed, 1.0, 40.0, iv_noise) for seed in range(20)]
    assert float(np.mean(ratios)) < 0.15
    assert max(ratios) < 0.15


@pytest.mark.parametrize("iv_noise", [0.0, 0.003])
def test_tref08_residual_shrinks_with_step(iv_noise: float) -> None:
    daily = np.mean([_ratio(seed, 1.0, 20.0, iv_noise) for seed in range(20)])
    quarter = np.mean([_ratio(seed, 0.25, 20.0, iv_noise) for seed in range(20)])
    sixteenth = np.mean([_ratio(seed, 1.0 / 16, 20.0, iv_noise) for seed in range(20)])
    assert quarter < 0.75 * daily
    assert sixteenth < 0.75 * quarter


def test_tref08_only_theta_when_nothing_moves() -> None:
    n = 10
    spots = np.full(n + 1, 100.0)
    ivs = np.full(n + 1, 0.30)
    marks = _marks(spots, ivs, 1.0, {CALL: -100, PUT: -100}, 0)
    days = attribute_life(marks, [], stock_code=STOCK, dividends={}, days_between=lambda a, b: 1.0)
    for a in days[1:]:
        assert a.delta == 0 and a.gamma == 0 and a.vega == 0
        assert a.theta > 0  # vendido em opções: o tempo paga
        assert abs(a.residual) < Decimal("0.01") * abs(a.theta)


# --- Invariante: mercado + execução = P&L pelos fluxos de caixa ---------------------------------


def _at(day: int) -> datetime:
    return datetime(2026, 1, 1, 15, 0, tzinfo=UTC) + timedelta(days=day)


def test_invariant_market_plus_execution_equals_cash_flows() -> None:
    book = PositionBook(
        STOCK,
        {
            CALL: OptionInfo(CALL, 1, True, date(2026, 3, 20), True),
            PUT: OptionInfo(PUT, 2, False, date(2026, 3, 20), True),
        },
    )
    entries = [
        LedgerEntry(1, EntryKind.ENTRY, CALL, -200, Decimal("4.10"), Decimal("1.10"), Decimal(0), _at(0), 1),
        LedgerEntry(2, EntryKind.ENTRY, PUT, -200, Decimal("3.95"), Decimal("1.05"), Decimal(0), _at(0), 2),
        LedgerEntry(3, EntryKind.HEDGE, STOCK, 60, Decimal("101.37"), Decimal("1.80"), Decimal("2"), _at(3)),
        LedgerEntry(4, EntryKind.HEDGE, STOCK, -25, Decimal("99.12"), Decimal("0.70"), Decimal(0), _at(5)),
        LedgerEntry(5, EntryKind.EXIT, PUT, 100, Decimal("3.20"), Decimal("0.40"), Decimal(0), _at(7), 2),
    ]
    ledger = replay(entries, book)
    rng = np.random.default_rng(7)
    spots = 100.0 * np.exp(np.cumsum(np.concatenate([[0.0], rng.normal(0, 0.02, 9)])))
    ivs = 0.30 + np.cumsum(np.concatenate([[0.0], rng.normal(0, 0.005, 9)]))
    dividends = {date(2026, 1, 1) + timedelta(days=6): Decimal("0.85")}
    marks = []
    for i in range(10):
        day = date(2026, 1, 1) + timedelta(days=i)
        q = {k: v for k, v in _holdings_at(ledger, day).items()}
        quotes = [
            LegQuote(CALL, True, K, T0_BD - i, float(ivs[i]), "observed"),
            LegQuote(PUT, False, K, T0_BD - i, float(ivs[i]), "observed"),
        ]
        legs = mark_legs(float(spots[i]), RATE_C, 0.0, quotes, q)
        marks.append(DayMark(day, Decimal(repr(round(float(spots[i]), 2))), q.get(STOCK, 0), legs))
    days = attribute_life(
        marks, ledger.transactions, stock_code=STOCK, dividends=dividends, days_between=lambda a, b: 1
    )
    total = sum((a.total for a in days), Decimal(0))
    # Fluxos de caixa: −q·preço − custos, proventos recebidos pela ação mantida e o valor final.
    cash = sum((-Decimal(tx.quantity) * tx.price - tx.costs for tx in ledger.transactions), Decimal(0))
    for m_prev, m in itertools.pairwise(marks):
        cash += Decimal(m_prev.stock_qty) * dividends.get(m.day, Decimal(0))
    final = marks[-1]
    cash += final.value(_holdings_at(ledger, final.day), STOCK)
    assert total == cash


def _holdings_at(ledger, day: date) -> dict[str, int]:  # type: ignore[no-untyped-def]
    from vollab.quant.journal import holdings_until

    return holdings_until(ledger, day)


def test_error_flag_limits_are_strict() -> None:
    from vollab.quant.attribution import AttributionDay

    def day(res: str, delta: str) -> AttributionDay:
        d = Decimal(delta)
        return AttributionDay(
            date(2026, 1, 2),
            d,
            Decimal(0),
            Decimal(0),
            Decimal(0),
            d + Decimal(res),
            Decimal(res),
            Decimal(0),
            False,
        )

    # 15% de 1000 = 150: igual não dispara; acima dispara (e acima de R$ 50).
    assert not error_flag(day("150", "1000"), max_ratio=0.15, min_brl=50)
    assert error_flag(day("150.01", "1000"), max_ratio=0.15, min_brl=50)
    # Resíduo relativo alto, mas igual ao mínimo em R$: não dispara.
    assert not error_flag(day("50", "10"), max_ratio=0.15, min_brl=50)
    assert error_flag(day("50.01", "10"), max_ratio=0.15, min_brl=50)
