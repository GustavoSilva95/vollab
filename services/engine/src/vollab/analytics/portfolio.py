"""Carteira, stress e limites (PRD 1.10 §5.9; BRD 1.7 RF-RSK-01..04, QA-12, PR-04).

Calculado na leitura a partir da **última marcação D-1** de cada operação aberta (nada é gravado).
O pró-forma soma uma posição nova (do simulador) à carteira para mostrar os limites com ela.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, defer

from vollab.analytics.crisis import CrisisValue, crisis_scenarios, crisis_values
from vollab.analytics.journal import status_of
from vollab.analytics.params import (
    RiskParams,
    SizingParams,
    risk_params_from_config,
    sizing_params_from_config,
)
from vollab.api.schemas.portfolio import (
    ExposureOut,
    LimitOut,
    LimitsResponse,
    PnlByExpiry,
    PnlByTicker,
    PortfolioResponse,
    ScenarioOut,
    ShockOut,
)
from vollab.collection.params import ensure_config_version
from vollab.db.models import DailyMark, Position
from vollab.quant.risk import (
    Book,
    Exposure,
    LimitsConfig,
    LimitState,
    RiskLeg,
    RiskStock,
    Scenario,
    ScenarioResult,
    Shock,
    evaluate_limits,
    exposures,
    run_scenario,
    standard_scenarios,
)

# Sem números no texto: percentual só existe na camada de exibição (PRD §5.1); os choques vão em decimal.
LABELS = {
    "gap_up": "Alta do ativo",
    "gap_down": "Queda do ativo",
    "vol_up": "Alta de vol",
    "down_vol_up": "Queda do ativo com alta de vol",
}


def _m(value: float) -> str:
    return str(Decimal(repr(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def _exp_out(e: Exposure, ticker: str | None = None, expiry: date | None = None) -> ExposureOut:
    return ExposureOut(
        ticker=ticker,
        expiry=expiry,
        delta_shares=e.delta_shares,
        delta_brl=e.delta_brl,
        gamma=e.gamma,
        gamma_1pct_brl=e.gamma_1pct_brl,
        vega_per_point_brl=e.vega_per_point_brl,
        theta_per_bd_brl=e.theta_per_bd_brl,
        market_value_brl=e.market_value_brl,
    )


class PortfolioComputer:
    def __init__(self, session: Session, *, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id
        version = ensure_config_version(session, user_id=user_id)
        session.commit()
        self.risk: RiskParams = risk_params_from_config(version)
        self.size: SizingParams = sizing_params_from_config(version)

    # Livro da carteira ---------------------------------------------------------------------------

    def book(self) -> tuple[Book, dict[str, date], list[str], int]:
        positions = self.session.scalars(
            select(Position)
            .options(defer(Position.decision_snapshot))
            .where(Position.user_id == self.user_id)
            .order_by(Position.id)
        ).all()
        ledgers = status_of(self.session, positions)
        warnings: list[str] = [
            f"Operação {p.id}: lançamentos inconsistentes ({ledgers[p.id][0].error}); fora da carteira."
            for p in positions
            if ledgers[p.id][0].error
        ]
        open_ = [p for p in positions if ledgers[p.id][0].is_open and not ledgers[p.id][0].error]
        if not open_:
            return Book([], [], {}), {}, warnings, 0
        ids = [p.id for p in open_]
        marks = {
            m.position_id: m
            for m in self.session.scalars(
                select(DailyMark)
                .where(DailyMark.position_id.in_(ids))
                .order_by(DailyMark.position_id, DailyMark.trade_date.desc())
                .ext(distinct_on(DailyMark.position_id))
            )
        }
        legs: list[RiskLeg] = []
        stocks: list[RiskStock] = []
        spots: dict[str, float] = {}
        dates: dict[str, date] = {}
        for p in open_:
            m = marks.get(p.id)
            if m is None:
                warnings.append(f"Operação {p.id} ({p.ticker}) ainda sem marcação D-1: fora da carteira.")
                continue
            ledger = ledgers[p.id][0]
            in_mark = {leg["code"]: leg["quantity"] for leg in m.legs} | {p.ticker: m.stock_qty}
            if any(
                ledger.holdings.get(k, 0) != in_mark.get(k, 0) for k in set(ledger.holdings) | set(in_mark)
            ):
                warnings.append(
                    f"Operação {p.id}: há lançamentos depois da marcação de {m.trade_date:%d/%m/%Y} "
                    "(a carteira usa as quantidades marcadas até a próxima marcação)."
                )
            if p.ticker not in dates or m.trade_date > dates[p.ticker]:
                dates[p.ticker] = m.trade_date
                spots[p.ticker] = float(m.spot)
            for leg in m.legs:
                if leg["quantity"] == 0 or "strike_eff" not in leg:
                    continue
                legs.append(
                    RiskLeg(
                        position_id=p.id,
                        ticker=p.ticker,
                        expiry=p.expiry,
                        code=leg["code"],
                        quantity=int(leg["quantity"]),
                        is_call=bool(leg["is_call"]),
                        strike_eff=float(leg["strike_eff"]),
                        days_to_expiry_bd=int(leg["days_to_expiry_bd"]),
                        iv=float(leg["iv"]) if leg["iv"] is not None else 0.0,
                        rate_c=float(leg["rate_c"]),
                        pv_div=float(leg["pv_div"]),
                    )
                )
            if m.stock_qty:
                stocks.append(RiskStock(p.id, p.ticker, p.expiry, m.stock_qty))
        for p in open_:
            m = marks.get(p.id)
            if m is not None and m.trade_date != dates.get(p.ticker):
                warnings.append(
                    f"Operação {p.id}: marcação de {m.trade_date:%d/%m/%Y}, mais antiga que a do ativo "
                    f"({dates[p.ticker]:%d/%m/%Y})."
                )
        return Book(legs, stocks, spots), dates, warnings, len(open_)

    # Exposição -----------------------------------------------------------------------------------

    def view(self) -> PortfolioResponse:
        book, dates, warnings, n_open = self.book()
        total = exposures(book, "total").get("total")
        by_t = exposures(book, "ticker")
        by_e = exposures(book, "expiry")
        return PortfolioResponse(
            positions_open=n_open,
            mark_dates=dates,
            warnings=warnings,
            total=_exp_out(total) if total is not None else None,
            by_ticker=[
                _exp_out(e, ticker=cast(str, k)) for k, e in sorted(by_t.items(), key=lambda x: str(x[0]))
            ],
            by_expiry=[
                _exp_out(e, ticker=cast(tuple[str, date], k)[0], expiry=cast(tuple[str, date], k)[1])
                for k, e in sorted(by_e.items(), key=lambda x: cast(tuple[str, date], x[0]))
            ],
        )

    # Stress e limites ----------------------------------------------------------------------------

    def crisis(self, tickers: Sequence[str]) -> list[CrisisValue]:
        return crisis_values(self.session, self.risk, tickers, user_id=self.user_id)

    def scenarios(self, book: Book) -> tuple[list[Scenario], dict[str, str], dict[str, str]]:
        tickers = sorted(book.spots)
        std = standard_scenarios(tickers, self.risk.stress_gap, self.risk.stress_vol_pts)
        values = self.crisis(tickers)
        crisis = crisis_scenarios(values) if tickers else []
        labels: dict[str, str] = {}
        origins: dict[str, str] = {}
        for sc in std:
            labels[sc.name] = LABELS[sc.name]
            origins[sc.name] = "estimated"
        ep_labels = {e.key: e.label for e in self.risk.crisis_episodes}
        for sc in crisis:
            key = sc.name.removeprefix("crisis_")
            labels[sc.name] = f"Crise {ep_labels.get(key, key)}"
            manual = all(v.origin == "manual" for v in values if v.episode == key and v.status == "ok")
            origins[sc.name] = "manual" if manual and sc.shocks else "approximate"
        return [*std, *crisis], labels, origins

    def scenario_out(
        self, r: ScenarioResult, label: str, kind: str, origin: str, shocks: dict[str, Shock]
    ) -> ScenarioOut:
        return ScenarioOut(
            name=r.name,
            label=label,
            kind=cast(Any, kind),
            pnl_brl=_m(r.pnl_total),
            loss_brl=_m(r.loss),
            by_ticker=[PnlByTicker(ticker=t, pnl_brl=_m(v)) for t, v in sorted(r.pnl_by_ticker.items())],
            by_expiry=[
                PnlByExpiry(ticker=t, expiry=e, pnl_brl=_m(v))
                for (t, e), v in sorted(r.pnl_by_expiry.items())
            ],
            missing_tickers=list(r.missing_tickers),
            origin=cast(Any, origin),
            shocks=[
                ShockOut(ticker=t, spot_shock=sh.spot, vol_shock=sh.vol) for t, sh in sorted(shocks.items())
            ],
        )

    def custom(self, spot_shock: float, vol_shock: float) -> ScenarioOut:
        book, *_ = self.book()
        sc = Scenario("custom", dict.fromkeys(book.spots, Shock(spot_shock, vol_shock)))
        return self.scenario_out(
            run_scenario(book, sc), "Cenário avulso", "custom", "estimated", dict(sc.shocks)
        )

    def limits(self, extra: Book | None = None, capital: float | None = None) -> LimitsResponse:
        book, _, warnings, _ = self.book()
        if extra is not None:
            book = Book(
                [*book.legs, *extra.legs], [*book.stocks, *extra.stocks], {**book.spots, **extra.spots}
            )
        scs, labels, origins = self.scenarios(book)
        results = [run_scenario(book, sc) for sc in scs]
        shocks = {sc.name: dict(sc.shocks) for sc in scs}
        cap = capital if capital is not None else self.size.capital_brl
        total = exposures(book, "total").get("total")
        vega = total.vega_per_point_brl if total is not None else 0.0
        lim = self.risk.limits
        cfg = LimitsConfig(
            lim.max_stress_loss_fraction,
            lim.max_abs_vega_fraction,
            lim.max_underlying_share,
            lim.max_expiry_share,
        )
        evaluated = evaluate_limits(results, vega, cap, cfg)
        out = [
            LimitOut(
                name=cast(Any, x.name),
                scope=x.scope,
                value=x.value,
                limit=x.limit,
                usage=x.usage,
                state=cast(Any, x.state.value),
                reason=x.reason,
            )
            for x in evaluated
        ]
        missing = sorted({t for r in results for t in r.missing_tickers})
        if missing:
            warnings.append(
                "Cenário de crise indisponível para " + ", ".join(missing) + ": limites calculados sem ele."
            )
        return LimitsResponse(
            capital_brl=_m(cap) if cap is not None else None,
            scenarios=[
                self.scenario_out(
                    r,
                    labels[r.name],
                    "crisis" if r.name.startswith("crisis_") else "standard",
                    origins[r.name],
                    shocks[r.name],
                )
                for r in results
            ],
            limits=out,
            breached=any(x.state is LimitState.BREACHED for x in evaluated),
            warnings=warnings,
        )
