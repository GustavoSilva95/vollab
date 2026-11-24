"""Carteira, stress e limites (PRD 1.10 §5.9; BRD 1.7 RF-RSK-01..04, QA-12, PR-04).

Puro, sem I/O. Reprecificação completa e **instantânea** por BS de cada perna (sem passar o tempo),
com o hedge atual e sem custos de saída. Choques: relativo no preço do ativo-objeto e em pontos de
vol (decimal) somados à IV de todas as pernas do ativo; IV nunca abaixo de `IV_FLOOR`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from vollab.quant.pricing import BUSINESS_DAYS_PER_YEAR, bs_greeks, bs_price

IV_FLOOR = 0.01


@dataclass(frozen=True, slots=True)
class RiskLeg:
    position_id: int
    ticker: str
    expiry: date
    code: str
    quantity: int
    is_call: bool
    strike_eff: float
    days_to_expiry_bd: int
    iv: float
    rate_c: float
    pv_div: float


@dataclass(frozen=True, slots=True)
class RiskStock:
    position_id: int
    ticker: str
    expiry: date  # vencimento da operação (para a exposição por vencimento)
    quantity: int


@dataclass(frozen=True, slots=True)
class Book:
    legs: Sequence[RiskLeg]
    stocks: Sequence[RiskStock]
    spots: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Exposure:
    delta_shares: float
    delta_brl: float
    gamma: float
    gamma_1pct_brl: float  # P&L de um movimento de 1%: ½·Γ·(0,01·S)²
    vega_per_point_brl: float
    theta_per_bd_brl: float
    market_value_brl: float


def _leg_values(leg: RiskLeg, spot: float, vol_shift: float) -> float:
    if leg.days_to_expiry_bd <= 0:
        return max(spot - leg.strike_eff, 0.0) if leg.is_call else max(leg.strike_eff - spot, 0.0)
    t = leg.days_to_expiry_bd / BUSINESS_DAYS_PER_YEAR
    iv = max(leg.iv + vol_shift, IV_FLOOR)
    return float(bs_price(spot, leg.strike_eff, t, leg.rate_c, iv, leg.is_call, leg.pv_div))


def exposures(book: Book, key: str) -> dict[object, Exposure]:
    """Greeks agregados por chave: `ticker`, `expiry` (ativo, vencimento) ou `total`."""

    def k(item: RiskLeg | RiskStock) -> object:
        if key == "ticker":
            return item.ticker
        if key == "expiry":
            return (item.ticker, item.expiry)
        return "total"

    acc: dict[object, list[float]] = {}
    for st in book.stocks:
        s = book.spots[st.ticker]
        a = acc.setdefault(k(st), [0.0] * 7)
        a[0] += st.quantity
        a[1] += st.quantity * s
        a[6] += st.quantity * s
    for leg in book.legs:
        s = book.spots[leg.ticker]
        a = acc.setdefault(k(leg), [0.0] * 7)
        if leg.days_to_expiry_bd <= 0:
            a[6] += leg.quantity * _leg_values(leg, s, 0.0)
            continue
        g = bs_greeks(
            s,
            leg.strike_eff,
            leg.days_to_expiry_bd / BUSINESS_DAYS_PER_YEAR,
            leg.rate_c,
            leg.iv,
            leg.is_call,
            leg.pv_div,
        )
        q = leg.quantity
        a[0] += q * float(g.delta)
        a[1] += q * float(g.delta) * s
        a[2] += q * float(g.gamma)
        a[3] += q * 0.5 * float(g.gamma) * (0.01 * s) ** 2
        a[4] += q * float(g.vega_per_point)
        a[5] += q * float(g.theta_per_bd)
        a[6] += q * float(g.price)
    return {key_: Exposure(*vals) for key_, vals in acc.items()}


@dataclass(frozen=True, slots=True)
class Shock:
    spot: float  # relativo (−0,10 = queda de 10%)
    vol: float  # pontos de vol em decimal


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    # Choque por ativo; ativos ausentes ficam sem choque (cenário indisponível para eles).
    shocks: Mapping[str, Shock]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    pnl_total: float
    pnl_by_ticker: dict[str, float]
    pnl_by_expiry: dict[tuple[str, date], float]
    pnl_by_position: dict[int, float]
    missing_tickers: tuple[str, ...]

    @property
    def loss(self) -> float:
        return -self.pnl_total


def run_scenario(book: Book, sc: Scenario) -> ScenarioResult:
    by_t: dict[str, float] = {}
    by_e: dict[tuple[str, date], float] = {}
    by_p: dict[int, float] = {}
    missing: set[str] = set()

    def add(ticker: str, expiry: date, pid: int, pnl: float) -> None:
        by_t[ticker] = by_t.get(ticker, 0.0) + pnl
        by_e[(ticker, expiry)] = by_e.get((ticker, expiry), 0.0) + pnl
        by_p[pid] = by_p.get(pid, 0.0) + pnl

    for st in book.stocks:
        shock = sc.shocks.get(st.ticker)
        if shock is None:
            missing.add(st.ticker)
            continue
        add(st.ticker, st.expiry, st.position_id, st.quantity * book.spots[st.ticker] * shock.spot)
    for leg in book.legs:
        shock = sc.shocks.get(leg.ticker)
        if shock is None:
            missing.add(leg.ticker)
            continue
        s0 = book.spots[leg.ticker]
        s1 = s0 * (1.0 + shock.spot)
        pnl = leg.quantity * (_leg_values(leg, s1, shock.vol) - _leg_values(leg, s0, 0.0))
        add(leg.ticker, leg.expiry, leg.position_id, pnl)
    return ScenarioResult(sc.name, sum(by_t.values()), by_t, by_e, by_p, tuple(sorted(missing)))


def standard_scenarios(tickers: Sequence[str], gap: float, vol_pts: float) -> list[Scenario]:
    """Os quatro stresses simples de RF-RSK-03, iguais para todos os ativos."""

    def same(shock: Shock) -> dict[str, Shock]:
        return dict.fromkeys(tickers, shock)

    return [
        Scenario("gap_up", same(Shock(gap, 0.0))),
        Scenario("gap_down", same(Shock(-gap, 0.0))),
        Scenario("vol_up", same(Shock(0.0, vol_pts))),
        Scenario("down_vol_up", same(Shock(-gap, vol_pts))),
    ]


# --- Limites (RF-RSK-04) ---------------------------------------------------------------------


class LimitState(StrEnum):
    OK = "ok"
    BREACHED = "breached"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class LimitsConfig:
    max_stress_loss_fraction: float
    max_abs_vega_fraction: float
    max_underlying_share: float
    max_expiry_share: float


@dataclass(frozen=True, slots=True)
class LimitResult:
    name: str
    scope: str | None  # ativo ou "ativo vencimento"
    value: float | None  # o que é comparado com o limite (fração)
    limit: float
    usage: float | None  # value / limit
    state: LimitState
    reason: str | None = None


def _state(value: float, limit: float) -> LimitState:
    return LimitState.BREACHED if value > limit else LimitState.OK


def evaluate_limits(
    results: Sequence[ScenarioResult], vega_total: float, capital: float | None, cfg: LimitsConfig
) -> list[LimitResult]:
    """Estado de cada limite; comparação estrita (igual ao limite é `ok`)."""
    names = [
        ("stress_loss", cfg.max_stress_loss_fraction),
        ("vega_total", cfg.max_abs_vega_fraction),
        ("underlying_concentration", cfg.max_underlying_share),
        ("expiry_concentration", cfg.max_expiry_share),
    ]
    if capital is None or capital <= 0:
        return [
            LimitResult(n, None, None, lim, None, LimitState.UNAVAILABLE, "informe o capital (RN-SIZ-01)")
            for n, lim in names
        ]
    out: list[LimitResult] = []
    worst = max((r.loss for r in results), default=0.0)
    v = max(worst, 0.0) / capital
    out.append(
        LimitResult(
            "stress_loss",
            None,
            v,
            cfg.max_stress_loss_fraction,
            v / cfg.max_stress_loss_fraction,
            _state(v, cfg.max_stress_loss_fraction),
        )
    )
    v = abs(vega_total) / capital
    out.append(
        LimitResult(
            "vega_total",
            None,
            v,
            cfg.max_abs_vega_fraction,
            v / cfg.max_abs_vega_fraction,
            _state(v, cfg.max_abs_vega_fraction),
        )
    )
    budget = cfg.max_stress_loss_fraction * capital
    tickers = sorted({t for r in results for t in r.pnl_by_ticker})
    for t in tickers:
        loss = max((-r.pnl_by_ticker.get(t, 0.0) for r in results), default=0.0)
        v = max(loss, 0.0) / budget
        out.append(
            LimitResult(
                "underlying_concentration",
                t,
                v,
                cfg.max_underlying_share,
                v / cfg.max_underlying_share,
                _state(v, cfg.max_underlying_share),
            )
        )
    expiries = sorted({e for r in results for e in r.pnl_by_expiry})
    for e in expiries:
        loss = max((-r.pnl_by_expiry.get(e, 0.0) for r in results), default=0.0)
        v = max(loss, 0.0) / budget
        out.append(
            LimitResult(
                "expiry_concentration",
                f"{e[0]} {e[1].isoformat()}",
                v,
                cfg.max_expiry_share,
                v / cfg.max_expiry_share,
                _state(v, cfg.max_expiry_share),
            )
        )
    return out
