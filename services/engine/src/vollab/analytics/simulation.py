"""Simulador e dimensionamento a partir dos dados gravados (PRD 1.9 §5.8; RF-SIM-01..05, RN-SIZ-01..06).

Endpoint de cálculo: lê os insumos já gravados pelo worker (OHLC, IV de referência, previsões,
spreads) e nunca grava. Reaproveita do ranking a previsão do modelo escolhido, o spread normal, os
spreads por faixa e o limiar (mesmas regras da §5.6.1), aplicados à estrutura real.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal, cast

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from vollab.analytics.crisis import crisis_values
from vollab.analytics.events import EventContext
from vollab.analytics.market import DividendInfo, load_daily_series, load_dividends, underlying_isin
from vollab.analytics.params import (
    RiskParams,
    SimulationParams,
    SizingParams,
    risk_params_from_config,
    simulation_params_from_config,
    sizing_params_from_config,
)
from vollab.analytics.portfolio import PortfolioComputer
from vollab.analytics.ranking import RankingComputer
from vollab.api.schemas.simulation import (
    ChainResponse,
    ChainSeries,
    CostsOut,
    DistributionOut,
    GreeksOut,
    LegOut,
    PayoffCurve,
    PayoffOut,
    PercentileOut,
    SimulationRequest,
    SimulationResponse,
    SizingOut,
    SizingRequest,
    SizingResponse,
    StockOut,
    StressOut,
)
from vollab.db.models import (
    ConfigVersion,
    DailyBar,
    OptionDailyQuote,
    OptionDailyStat,
    OptionSeries,
    Underlying,
)
from vollab.quant.calendar import business_days, count_business_days
from vollab.quant.costs import Band, hedge_cost, moneyness_band, spread_estimate
from vollab.quant.edge import Direction, EdgeState, classify, premium
from vollab.quant.pricing import (
    BUSINESS_DAYS_PER_YEAR,
    IvStatus,
    bs_greeks,
    bs_price,
    continuous_rate,
    implied_vol,
)
from vollab.quant.risk import Book, RiskLeg, RiskStock
from vollab.quant.simulation import (
    DYNAMIC_HEDGE,
    STRUCTURE_DIRECTION,
    Distribution,
    HedgeRule,
    Leg,
    Market,
    StressScenario,
    Structure,
    initial_hedge,
    kamal_derman_std,
    payoff_curve,
    rescale_returns,
    simulate_paths,
    stock_quantity,
    stress_losses,
    structure_greeks,
    structure_iv,
    summarize,
    validate_legs,
)
from vollab.quant.sizing import SizingInput, size_position
from vollab.settings import get_settings

Origin = Literal["observed", "estimated", "manual", "approximate"]
_CENT = Decimal("0.01")
IV_STATUS_TEXT = {
    IvStatus.BELOW_INTRINSIC: "preço abaixo do valor intrínseco",
    IvStatus.ABOVE_UPPER_BOUND: "preço acima do limite de arbitragem",
    IvStatus.NOT_CONVERGED: "cálculo da IV não convergiu",
    IvStatus.INVALID_INPUT: "entrada inválida",
    IvStatus.OUT_OF_RANGE: "IV fora do intervalo aceito",
}


class SimulationInputError(ValueError):
    """Insumo inválido ou ausente: a rota devolve 422 com a mensagem (sem número inventado)."""


def money(value: float) -> str:
    return str(Decimal(repr(float(value))).quantize(_CENT, rounding=ROUND_HALF_EVEN))


def _join(*parts: str | None) -> str | None:
    out = "; ".join(p for p in parts if p)
    return out or None


@dataclass(frozen=True, slots=True)
class _SeriesRow:
    series: OptionSeries
    strike: float
    quote: OptionDailyQuote | None
    trades_count: int | None


@dataclass
class Computed:
    """Resultado interno: a resposta e os números que o dimensionamento e o registro usam."""

    response: SimulationResponse
    legs: list[Leg]
    vega_unit: float  # |vega| da estrutura por 1,00 de vol, por unidade (BRL)
    distribution: Distribution | None
    stress: list[StressOut]
    stress_max_unit: float | None
    stress_notes: list[str]
    market: Market
    stock_qty: int
    dynamic: bool
    p_low: float | None
    p_high: float | None
    cost_sell: float | None
    cost_buy: float | None


@dataclass(frozen=True, slots=True)
class StructureEdge:
    """Só o edge e o semáforo de uma estrutura, sem distribuição, stress e payoff (rolagem, §5.10)."""

    as_of: date
    expiry: date
    horizon_bd: int
    state: str
    signal_direction: Direction | None
    direction_match: bool
    reason: str | None
    iv: float
    sigma: float | None
    premium: float | None
    p_low: float | None
    p_high: float | None
    cost_sell: float | None
    cost_buy: float | None
    extra_cost_vol_pts: float | None
    net_relative: float | None
    vega_unit: float
    legs: list[tuple[int, str]]


class SimulationComputer:
    def __init__(self, session: Session, *, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id
        self.rk = RankingComputer(session, user_id=user_id)  # garante a versão de configuração vigente
        version = session.get(ConfigVersion, self.rk.p.version_id)
        if version is None:  # pragma: no cover (acabou de ser criada ou lida)
            raise RuntimeError("configuração vigente não encontrada")
        self.sim: SimulationParams = simulation_params_from_config(version)
        self.size: SizingParams = sizing_params_from_config(version)
        self.risk: RiskParams = risk_params_from_config(version)
        self.holidays = self.rk.holidays
        self.v = self.rk.v

    # Insumos comuns ---------------------------------------------------------------------------

    def _underlying(self, ticker: str) -> str:
        found = self.session.scalar(
            select(Underlying.ticker).where(Underlying.user_id == self.user_id, Underlying.ticker == ticker)
        )
        if found is None:
            raise LookupError("Ativo não cadastrado.")
        isin = underlying_isin(self.session, ticker)
        if isin is None:
            raise SimulationInputError("Ativo sem ISIN: rode a coleta antes de simular.")
        return isin

    def _as_of(self, ticker: str) -> DailyBar | None:
        return self.session.scalars(
            select(DailyBar)
            .where(DailyBar.ticker == ticker, DailyBar.trade_date <= self.rk.expected_as_of)
            .order_by(DailyBar.trade_date.desc())
            .limit(1)
        ).first()

    def _dividends_until(
        self, dividends: dict[date, DividendInfo], as_of: date, expiry: date
    ) -> tuple[tuple[tuple[int, float], ...], float]:
        """Proventos com data ex em (as_of, expiry]: (índice do pregão, valor) e a soma nominal."""
        out = []
        total = 0.0
        for ex, info in sorted(dividends.items()):
            if as_of < ex <= expiry:
                out.append((count_business_days(as_of, ex, self.holidays), info.amount))
                total += info.amount
        return tuple(out), total

    def _series_rows(
        self, ids: list[int] | None, isin: str, as_of: date, expiry: date | None
    ) -> list[_SeriesRow]:
        stmt = (
            select(OptionSeries, OptionDailyStat.strike, OptionDailyQuote, OptionDailyStat.trades_count)
            .outerjoin(
                OptionDailyStat,
                (OptionDailyStat.series_id == OptionSeries.id) & (OptionDailyStat.trade_date == as_of),
            )
            .outerjoin(
                OptionDailyQuote,
                (OptionDailyQuote.series_id == OptionSeries.id) & (OptionDailyQuote.trade_date == as_of),
            )
            .where(OptionSeries.underlying_isin == isin, OptionSeries.expiry > as_of)
        )
        if ids is not None:
            stmt = stmt.where(OptionSeries.id.in_(ids))
        if expiry is not None:
            stmt = stmt.where(OptionSeries.expiry == expiry)
        rows = self.session.execute(stmt.order_by(OptionSeries.expiry, OptionSeries.strike)).all()
        return [
            _SeriesRow(r[0], float(r[1]) if r[1] is not None else float(r[0].strike), r[2], r[3])
            for r in rows
        ]

    # Cadeia (montagem das pernas) ---------------------------------------------------------------

    def chain(self, ticker: str, expiry: date | None) -> ChainResponse:
        isin = self._underlying(ticker)
        bar = self._as_of(ticker)
        empty = ChainResponse(
            ticker=ticker,
            as_of=None,
            spot_brl=None,
            expiries=[],
            expiries_with_iv=[],
            expiry=None,
            days_to_expiry_bd=None,
            forward=None,
            series=[],
            suggestions={},
        )
        if bar is None:
            return empty
        as_of = bar.trade_date
        expiries = sorted(
            set(
                self.session.scalars(
                    select(OptionSeries.expiry)
                    .join(OptionDailyStat, OptionDailyStat.series_id == OptionSeries.id)
                    .where(
                        OptionSeries.underlying_isin == isin,
                        OptionSeries.expiry > as_of,
                        OptionDailyStat.trade_date == as_of,
                    )
                    .distinct()
                )
            )
        )
        if not expiries:
            return empty.model_copy(update={"as_of": as_of, "spot_brl": money(float(bar.close))})
        with_iv = set(
            self.session.scalars(
                select(OptionSeries.expiry)
                .join(OptionDailyQuote, OptionDailyQuote.series_id == OptionSeries.id)
                .where(
                    OptionSeries.underlying_isin == isin,
                    OptionSeries.expiry > as_of,
                    OptionDailyQuote.trade_date == as_of,
                    OptionDailyQuote.iv.is_not(None),
                )
                .distinct()
            )
        )
        monthly = set(
            self.session.scalars(
                select(OptionSeries.expiry)
                .where(OptionSeries.underlying_isin == isin, OptionSeries.expiry.in_(expiries))
                .where(OptionSeries.is_weekly.is_(False))
                .distinct()
            )
        )
        # Padrão: o primeiro vencimento com IV de referência; sem nenhum, o primeiro mensal.
        default = min(with_iv) if with_iv else min(monthly, default=expiries[0])
        chosen = expiry if expiry in expiries else default
        spot = float(bar.close)
        rate = self.rk.rates.on(as_of)
        h = count_business_days(as_of, chosen, self.holidays)
        rate_c = continuous_rate(rate) if rate is not None else 0.0
        t = h / BUSINESS_DAYS_PER_YEAR
        divs, total = self._dividends_until(load_dividends(self.session, ticker), as_of, chosen)
        pv = Market(spot, rate_c, h, divs).pv_dividends(0)
        forward = (spot - pv) * math.exp(rate_c * t)
        protected = self.rk.p.vol.implied.dividend_protected_strikes
        out: list[ChainSeries] = []
        for row in self._series_rows(None, isin, as_of, chosen):
            k_eff = row.strike - total if protected else row.strike
            q = row.quote
            iv = q.iv if q is not None and q.iv is not None else None
            price = None
            if iv is not None and h > 0:
                price = money(
                    float(bs_price(spot, k_eff, t, rate_c, iv, row.series.option_type == "call", pv))
                )
            out.append(
                ChainSeries(
                    series_id=row.series.id,
                    code=row.series.code,
                    option_type=cast(Literal["call", "put"], row.series.option_type),
                    expiry=row.series.expiry,
                    strike=row.strike,
                    effective_strike=k_eff,
                    k_over_f=k_eff / forward,
                    iv=iv,
                    price_brl=price,
                    liquid=bool(q.liquid) if q is not None else False,
                    trades_count=row.trades_count,
                )
            )
        return ChainResponse(
            ticker=ticker,
            as_of=as_of,
            spot_brl=money(spot),
            expiries=expiries,
            expiries_with_iv=sorted(with_iv),
            expiry=chosen,
            days_to_expiry_bd=h,
            forward=forward,
            series=out,
            suggestions=self._suggest(out),
        )

    def _suggest(self, series: list[ChainSeries]) -> dict[str, list[int]]:
        """Straddle no strike mais próximo de F; strangle e venda coberta em K/F = skew (0,95 e 1,05).
        Prefere séries com IV de referência."""
        priced = [s for s in series if s.iv is not None] or series
        calls = [s for s in priced if s.option_type == "call"]
        puts = [s for s in priced if s.option_type == "put"]
        out: dict[str, list[int]] = {}
        lo, hi = self.rk.p.edge.skew_moneyness
        if calls and puts:
            strikes = {s.effective_strike for s in calls} & {s.effective_strike for s in puts}
            if strikes:
                k = min(strikes, key=lambda x: abs(x / (calls[0].effective_strike / calls[0].k_over_f) - 1.0))
                c = next(s for s in calls if s.effective_strike == k)
                p = next(s for s in puts if s.effective_strike == k)
                out["short_straddle"] = out["long_straddle"] = [c.series_id, p.series_id]
            put = min(puts, key=lambda s: abs(s.k_over_f - lo))
            call = min(calls, key=lambda s: abs(s.k_over_f - hi))
            if put.effective_strike < call.effective_strike:
                out["short_strangle"] = out["long_strangle"] = [put.series_id, call.series_id]
        if calls:
            out["covered_call"] = [min(calls, key=lambda s: abs(s.k_over_f - hi)).series_id]
        return out

    # Simulação ---------------------------------------------------------------------------------

    def compute(self, req: SimulationRequest) -> Computed:
        return cast(Computed, self._compute(req, extra_cost_brl_unit=0.0, edge_only=False))

    def structure_edge(self, req: SimulationRequest, *, extra_cost_brl_unit: float = 0.0) -> StructureEdge:
        """Edge e semáforo da estrutura (§5.8), somando aos custos um valor extra em R$ por unidade
        (rolagem: custo de fechar a posição atual ÷ opções da nova, PRD 1.11 §5.10)."""
        return cast(
            StructureEdge, self._compute(req, extra_cost_brl_unit=extra_cost_brl_unit, edge_only=True)
        )

    def _compute(
        self, req: SimulationRequest, *, extra_cost_brl_unit: float, edge_only: bool
    ) -> Computed | StructureEdge:
        ticker = req.ticker.upper()
        structure = Structure(req.structure)
        direction = STRUCTURE_DIRECTION[structure]
        isin = self._underlying(ticker)
        bar = self._as_of(ticker)
        if bar is None:
            raise SimulationInputError("Sem OHLC oficial do ativo: rode a coleta antes de simular.")
        as_of = bar.trade_date
        rows = {
            r.series.id: r for r in self._series_rows([leg.series_id for leg in req.legs], isin, as_of, None)
        }
        missing = [leg.series_id for leg in req.legs if leg.series_id not in rows]
        if missing:
            raise SimulationInputError(
                f"Série(s) {missing} inexistente(s), vencida(s) ou de outro ativo-objeto em {as_of:%d/%m/%Y}."
            )
        expiries = {rows[leg.series_id].series.expiry for leg in req.legs}
        if len(expiries) != 1:
            raise SimulationInputError("As pernas devem ter o mesmo vencimento.")
        expiry = expiries.pop()
        rate = self.rk.rates.on(as_of)
        if rate is None:
            raise SimulationInputError("Sem Selic no pregão de referência.")
        rate_c = continuous_rate(rate)
        h = count_business_days(as_of, expiry, self.holidays)
        if h < 1:
            raise SimulationInputError("Vencimento no próprio pregão de referência.")
        t = h / BUSINESS_DAYS_PER_YEAR
        dividends = load_dividends(self.session, ticker)
        divs, div_total = self._dividends_until(dividends, as_of, expiry)
        spot = float(req.manual_spot_brl) if req.manual_spot_brl is not None else float(bar.close)
        market = Market(spot, rate_c, h, divs)
        pv = market.pv_dividends(0)
        if spot - pv <= 0:
            raise SimulationInputError("Preço do ativo menor que o valor presente dos proventos.")
        forward = (spot - pv) * math.exp(rate_c * t)
        protected = self.rk.p.vol.implied.dividend_protected_strikes
        sign = -1 if direction is Direction.SELL else 1
        manual_used = req.manual_spot_brl is not None
        c = self.rk.p.costs
        lot = self.size.lot_size

        # Pernas: IV de referência ou preço manual (RF-SIM-03).
        legs: list[Leg] = []
        leg_info: list[tuple[_SeriesRow, float, Origin, Origin, datetime | None, Band]] = []
        spreads: list[float | None] = []
        for li in req.legs:
            row = rows[li.series_id]
            is_call = row.series.option_type == "call"
            k_eff = row.strike - div_total if protected else row.strike
            if li.manual_price_brl is not None:
                price = float(li.manual_price_brl)
                res = implied_vol(price, spot, k_eff, t, rate_c, is_call, pv)
                if int(res.status) != IvStatus.OK:
                    why = IV_STATUS_TEXT.get(IvStatus(int(res.status)), "sem solução")
                    raise SimulationInputError(f"Preço manual de {row.series.code} sem IV: {why}.")
                iv = float(res.iv)
                price_origin: Origin = "manual"
                iv_origin: Origin = "manual"
                manual_used = True
            else:
                q = row.quote
                if q is None or q.iv is None:
                    raise SimulationInputError(
                        f"{row.series.code} sem IV de referência em {as_of:%d/%m/%Y}: informe o preço manual."
                    )
                iv = float(q.iv)
                price = float(bs_price(spot, k_eff, t, rate_c, iv, is_call, pv))
                price_origin, iv_origin = "estimated", "observed"
            band = moneyness_band(k_eff / forward, c.moneyness_bands)
            est = spread_estimate(self.rk.spread_days(ticker, as_of, band))
            spreads.append(est.conservative if est else None)
            rel = est.conservative if est else 0.0
            legs.append(
                Leg(
                    is_call=is_call,
                    strike=k_eff,
                    quantity=sign,
                    iv=iv,
                    price=price,
                    entry_cost_rate=rel / 2.0 + c.option_fee_rate + c.brokerage_rate,
                    entry_cost_fixed=c.brokerage_per_order_brl / lot,
                )
            )
            leg_info.append((row, price, price_origin, iv_origin, li.manual_price_at, band))
        why_invalid = validate_legs(structure, legs)
        if why_invalid:
            raise SimulationInputError(f"Pernas não formam {structure.value}: {why_invalid}.")
        stock_qty = stock_quantity(structure)

        # Edge da estrutura (mesmas regras da §5.6.1).
        iv_raw = structure_iv(legs, market)
        ctx = EventContext(self.session, user_id=self.user_id, ticker=ticker, params=self.rk.p.vol)
        iv_ex, ex_reason, removed = ctx.ex_event_atm(as_of, expiry, h, iv_raw)
        approximate = iv_ex is None
        iv_used = iv_raw if iv_ex is None else iv_ex
        iv_note = _join("IV com evento: não foi possível separar o salto", ex_reason) if approximate else None
        iv_origin_s: Origin = "manual" if manual_used else ("approximate" if approximate else "observed")
        iv_ev = self.v.make(
            iv_used,
            as_of,
            origin=iv_origin_s,
            reason=_join(iv_note, f"{len(removed)} evento(s) removido(s)" if removed else None),
        )
        iv_with = self.v.make(iv_raw, as_of, origin="manual" if manual_used else "observed")
        model = self.rk.p.forecast.selected_model
        forecast = self.rk.forecast_value(ticker, as_of, h, model, approximate)
        ns_value, _ = self.rk.normal_spread_value(ticker, as_of)
        threshold = self.rk.threshold_value(as_of)
        g_unit = structure_greeks(legs, stock_qty, market)
        vega_unit = abs(g_unit.vega_per_point) * 100.0

        und = spread_estimate(self.rk.spread_days(ticker, as_of, Band.UNDERLYING))
        und_spread = und.conservative if und else c.tick_brl / spot
        lam = und_spread / 2.0 + c.underlying_fee_rate
        rule = HedgeRule(DYNAMIC_HEDGE[structure], self.sim.delta_band, lam)

        empty = self.v.missing(as_of, "sem dado")
        state: str = EdgeState.UNAVAILABLE.value
        reason: str | None = None
        signal_dir: Direction | None = None
        costs_out: CostsOut | None = None
        prem_ev = rel_ev = empty
        p_lo = p_hi = cost_sell = cost_buy = None
        net_premium = net_relative = None
        required_sell = required_buy = None
        sigma = forecast.value if forecast.status == "ok" else None
        derived: Origin = (
            "manual"
            if manual_used
            else ("approximate" if approximate or forecast.origin == "approximate" else "estimated")
        )
        missing_band = [info[0].series.code for info, s in zip(leg_info, spreads, strict=True) if s is None]
        if sigma is None:
            reason = forecast.reason or "sem previsão"
        else:
            lo, hi = forecast.ci_low or sigma, forecast.ci_high or sigma
            s_val = cast(float, ns_value.value)
            p = premium(iv_used, sigma, lo, hi, s_val)
            p_lo, p_hi = p.ci_low, p.ci_high
            prem_ev = self.v.make(p.value, as_of, origin=derived, ci=(p.ci_low, p.ci_high))
            rel_ev = self.v.make(
                p.value / sigma, as_of, origin=derived, ci=(p.ci_low / sigma, p.ci_high / sigma)
            )
            if missing_band:
                reason = (
                    f"sem estimativa de spread na faixa de {', '.join(missing_band)} nos últimos "
                    f"{c.spread_lookback_bd} pregões"
                )
            else:
                spread_brl = sum(cast(float, s) * leg.price for s, leg in zip(spreads, legs, strict=True))
                fees_brl = sum(2.0 * c.option_fee_rate * leg.price for leg in legs)
                brok_brl = sum(
                    2.0 * c.brokerage_rate * leg.price + 2.0 * c.brokerage_per_order_brl / lot for leg in legs
                )
                stock_brl = stock_qty * (und_spread * spot + 2.0 * c.underlying_fee_rate * spot)
                opt_pts = (spread_brl + fees_brl + brok_brl + stock_brl) / vega_unit
                extra_pts = extra_cost_brl_unit / vega_unit
                opt_pts += extra_pts
                hedge = hedge_cost(
                    sigma,
                    underlying_rel_spread=und_spread,
                    fee_rate=c.underlying_fee_rate,
                    interval_bd=c.hedge_interval_bd,
                )
                cost_sell = opt_pts + hedge.sell
                cost_buy = None if hedge.buy is None else opt_pts + hedge.buy
                costs_out = CostsOut(
                    options_spread_brl=money(spread_brl * lot),
                    options_fees_brl=money(fees_brl * lot),
                    options_brokerage_brl=money(brok_brl * lot),
                    stock_brl=money(stock_brl * lot),
                    underlying_spread=und_spread,
                    underlying_spread_estimated=und is not None,
                    options_vol_pts=opt_pts,
                    hedge_sell_vol_pts=hedge.sell,
                    hedge_buy_vol_pts=hedge.buy,
                    hedge_half_spread=hedge.half_spread,
                    hedge_interval_bd=c.hedge_interval_bd,
                    total_sell_vol_pts=cost_sell,
                    total_buy_vol_pts=cost_buy,
                    band_hedge_cost_brl=None,
                )
                sig = classify(
                    p,
                    forecast=sigma,
                    cost_sell=cost_sell,
                    cost_buy=cost_buy,
                    threshold=self.rk.p.edge.threshold_vol_pts,
                )
                state = sig.state.value
                signal_dir = sig.direction
                required_sell, required_buy = sig.required_sell, sig.required_buy
                # Prêmio líquido na direção **da estrutura** (pode ser negativo).
                if direction is Direction.SELL:
                    net_premium = p.value - cost_sell
                else:
                    net_premium = None if cost_buy is None else -p.value - cost_buy
                net_relative = None if net_premium is None else net_premium / sigma
                reason = _join(
                    iv_note,
                    "compra de vol inviável: o hedge consome todo o edge" if cost_buy is None else None,
                )

        direction_match = signal_dir is direction
        if state == EdgeState.EDGE.value and not direction_match:
            reason = _join(
                reason,
                f"o sinal é de {'compra' if signal_dir is Direction.BUY else 'venda'} de vol e a "
                f"estrutura é de {'venda' if direction is Direction.SELL else 'compra'}",
            )

        if edge_only:
            return StructureEdge(
                as_of=as_of,
                expiry=expiry,
                horizon_bd=h,
                state=state,
                signal_direction=signal_dir,
                direction_match=direction_match,
                reason=reason,
                iv=iv_used,
                sigma=sigma,
                premium=None if prem_ev.value is None else float(prem_ev.value),
                p_low=p_lo,
                p_high=p_hi,
                cost_sell=cost_sell,
                cost_buy=cost_buy,
                extra_cost_vol_pts=None if costs_out is None else extra_cost_brl_unit / vega_unit,
                net_relative=net_relative,
                vega_unit=vega_unit,
                legs=[(info[0].series.id, info[0].series.code) for info in leg_info],
            )

        # Distribuição simulada (QA-10).
        dist, dist_out = self._distribution(
            ticker, as_of, legs, stock_qty, market, rule, sigma, costs_out is not None, g_unit.vega_per_point
        )
        if costs_out is not None and dist is not None:
            costs_out.band_hedge_cost_brl = money(dist.mean_hedge_cost)

        # Stress (QA-09): os choques do bloco `risk` (os mesmos da carteira) e, desde a Etapa 7, os
        # cenários de crise medidos do ativo (QA-12).
        gap, vol = self.risk.stress_gap, self.risk.stress_vol_pts
        scenarios = [
            StressScenario("gap_down", -gap, 0.0),
            StressScenario("gap_up", gap, 0.0),
            StressScenario("vol_up", 0.0, vol),
            StressScenario("down_vol_up", -gap, vol),
        ]
        stress_notes: list[str] = []
        for cv in crisis_values(self.session, self.risk, [ticker], user_id=self.user_id):
            if cv.status == "ok" and cv.price_shock is not None and cv.vol_shock is not None:
                scenarios.append(StressScenario(f"crisis_{cv.episode}", cv.price_shock, cv.vol_shock))
            else:
                stress_notes.append(f"crise {cv.label} indisponível: {cv.reason or 'sem medição'}")
        exit_rates = [leg.entry_cost_rate for leg in legs]
        losses = stress_losses(legs, stock_qty, market, rule, scenarios, exit_cost_rates=exit_rates)
        stress = [
            StressOut(
                name=sl.scenario.name,
                spot_shock=sl.scenario.spot_shock,
                vol_shock=sl.scenario.vol_shock,
                loss_brl=money(sl.loss * lot),
            )
            for sl in losses
        ]
        stress_max = max(sl.loss for sl in losses)

        # Payoff (RF-SIM-02).
        payoff = self._payoff(legs, stock_qty, market, as_of)
        legs_out = []
        g_legs = bs_greeks(
            spot,
            np.array([leg.strike for leg in legs]),
            t,
            rate_c,
            np.array([leg.iv for leg in legs]),
            np.array([leg.is_call for leg in legs]),
            pv,
        )
        for i, (leg, info, spr) in enumerate(zip(legs, leg_info, spreads, strict=True)):
            row, price, p_origin, i_origin, p_at, band = info
            legs_out.append(
                LegOut(
                    series_id=row.series.id,
                    code=row.series.code,
                    option_type=cast(Literal["call", "put"], row.series.option_type),
                    quantity_per_lot=leg.quantity * lot,
                    strike=row.strike,
                    effective_strike=leg.strike,
                    k_over_f=leg.strike / forward,
                    band=cast(Literal["low", "atm", "high"], band.value),
                    price_brl=money(price),
                    price_origin=cast(Literal["observed", "estimated", "manual"], p_origin),
                    price_at=p_at,
                    iv=self.v.make(leg.iv, as_of, origin=i_origin),
                    delta=float(np.broadcast_to(g_legs.delta, (len(legs),))[i]),
                    gamma=float(np.broadcast_to(g_legs.gamma, (len(legs),))[i]),
                    vega_per_point=float(np.broadcast_to(g_legs.vega_per_point, (len(legs),))[i]),
                    theta_per_bd=float(np.broadcast_to(g_legs.theta_per_bd, (len(legs),))[i]),
                    spread_conservative=spr,
                )
            )

        def greeks(n: int) -> GreeksOut:
            return GreeksOut(
                delta_shares=g_unit.delta * n,
                gamma=g_unit.gamma * n,
                vega_per_point_brl=g_unit.vega_per_point * n,
                theta_per_bd_brl=g_unit.theta_per_bd * n,
            )

        settings = get_settings()
        response = SimulationResponse(
            ticker=ticker,
            structure=req.structure,
            direction=direction.value,
            dynamic_hedge=DYNAMIC_HEDGE[structure],
            as_of=as_of,
            expected_as_of=self.rk.expected_as_of,
            expiry=expiry,
            horizon_bd=h,
            lots=req.lots,
            lot_size=lot,
            spot_brl=money(spot),
            spot_origin="manual" if req.manual_spot_brl is not None else "observed",
            spot_at=req.manual_spot_at,
            rate=rate,
            legs=legs_out,
            stock=StockOut(quantity_per_lot=stock_qty * lot, price_brl=money(spot)) if stock_qty else None,
            iv=iv_ev,
            iv_with_events=iv_with,
            events_removed=removed,
            forecast=forecast,
            normal_spread=ns_value,
            premium=prem_ev,
            relative_edge=rel_ev,
            threshold=threshold,
            state=cast(Literal["edge", "inconclusive", "no_edge", "unavailable"], state),
            signal_direction=signal_dir.value if signal_dir else None,
            direction_match=direction_match,
            reason=reason,
            required_sell=required_sell,
            required_buy=required_buy,
            net_premium=net_premium,
            net_relative_edge=net_relative,
            expected_pnl_approx_brl=None if net_premium is None else money(vega_unit * net_premium * lot),
            costs=costs_out,
            greeks_lot=greeks(lot),
            greeks_position=greeks(lot * req.lots),
            payoff=payoff,
            distribution=dist_out,
            expected_pnl_brl=money(dist.mean) if dist is not None else None,
            model=model,
            ci_level=self.rk.p.vol.ci_level,
            config_version_id=self.rk.p.version_id,
            engine_version=settings.engine_version,
        )
        return Computed(
            response=response,
            legs=legs,
            vega_unit=vega_unit,
            distribution=dist,
            stress=stress,
            stress_max_unit=stress_max,
            stress_notes=stress_notes,
            market=market,
            stock_qty=stock_qty,
            dynamic=rule.dynamic,
            p_low=p_lo,
            p_high=p_hi,
            cost_sell=cost_sell,
            cost_buy=cost_buy,
        )

    def _distribution(
        self,
        ticker: str,
        as_of: date,
        legs: list[Leg],
        stock_qty: int,
        market: Market,
        rule: HedgeRule,
        sigma: float | None,
        has_costs: bool,
        vega_point_unit: float,
    ) -> tuple[Distribution | None, DistributionOut]:
        sp = self.sim
        lot = self.size.lot_size
        base: dict[str, Any] = {
            "paths": sp.paths,
            "seed": sp.seed,
            "sample_size": 0,
            "sample_start": None,
            "sample_end": None,
            "delta_band": sp.delta_band,
            "delta_band_calibrated": False,
            "iv_constant": True,
            "mean_brl": None,
            "std_brl": None,
            "variance_brl2": None,
            "percentiles": [],
            "es_level": self.size.es_level,
            "es_brl": None,
            "prob_loss": None,
            "mean_rehedges": None,
            "mean_band_hedge_cost_brl": None,
            "kamal_derman_std_brl": None,
            "hist_edges_brl": [],
            "hist_counts": [],
            "origin": "estimated",
        }
        series = load_daily_series(self.session, ticker, self.holidays, load_dividends(self.session, ticker))
        days: list[date] = []
        rets = np.empty(0)
        if series is not None:
            with np.errstate(divide="ignore", invalid="ignore"):
                r = np.log(series.close / series.prev_close_adj)
            idx = [i for i, d in enumerate(series.days) if d <= as_of and np.isfinite(r[i])]
            idx = idx[-sp.sample_bd :]
            days = [series.days[i] for i in idx]
            rets = r[idx]
        base |= {
            "sample_size": int(rets.size),
            "sample_start": days[0] if days else None,
            "sample_end": days[-1] if days else None,
        }
        if sigma is None:
            return None, DistributionOut(
                status="unavailable", reason="sem previsão de RV avaliada para reescalar a amostra", **base
            )
        if not has_costs:
            return None, DistributionOut(status="unavailable", reason="sem estimativa de custos", **base)
        if rets.size < sp.min_returns:
            return None, DistributionOut(
                status="insufficient_data",
                reason=f"{rets.size} de {sp.min_returns} retornos diários na amostra",
                **base,
            )
        z = rescale_returns(rets, sigma)
        result = simulate_paths(legs, stock_qty, market, rule, z, paths=sp.paths, seed=sp.seed)
        d = summarize(result, lot_size=lot, es_level=self.size.es_level, bins=sp.histogram_bins)
        kd = kamal_derman_std(vega_point_unit * lot, sigma, market.days_bd) if rule.dynamic else None
        base |= {
            "mean_brl": money(d.mean),
            "std_brl": money(d.std),
            "variance_brl2": d.variance,
            "percentiles": [PercentileOut(percentile=p, pnl_brl=money(v)) for p, v in d.percentiles.items()],
            "es_brl": money(d.es),
            "prob_loss": d.prob_loss,
            "mean_rehedges": d.mean_rehedges,
            "mean_band_hedge_cost_brl": money(d.mean_hedge_cost),
            "kamal_derman_std_brl": money(kd) if kd is not None else None,
            "hist_edges_brl": d.hist_edges,
            "hist_counts": d.hist_counts,
        }
        return d, DistributionOut(
            status="ok",
            reason=f"bootstrap de {rets.size} retornos reescalados para σ̂; IV constante; banda de delta "
            "não calibrada",
            **base,
        )

    def _payoff(self, legs: list[Leg], stock_qty: int, market: Market, as_of: date) -> PayoffOut:
        sp = self.sim
        lot = self.size.lot_size
        spots = np.linspace(
            market.spot * (1.0 - sp.payoff_range), market.spot * (1.0 + sp.payoff_range), sp.payoff_points
        )
        h = market.days_bd
        steps = [(0, "hoje")]
        if h >= 2:
            steps.append((h // 2, "metade da vida"))
        steps.append((h, "vencimento"))
        future = list(
            business_days(as_of + timedelta(days=1), as_of + timedelta(days=h * 2 + 15), self.holidays)
        )
        curves = []
        for step, label in steps:
            day = as_of if step == 0 else future[step - 1]
            pnl = payoff_curve(legs, stock_qty, market, spots, step) * lot
            curves.append(PayoffCurve(label=label, step_bd=step, day=day, pnl_brl=[float(x) for x in pnl]))
        return PayoffOut(spots=[float(x) for x in spots], curves=curves)

    # Dimensionamento ---------------------------------------------------------------------------

    def sizing(self, req: SizingRequest) -> tuple[Computed, SizingOut]:
        comp = self.compute(req)
        r = comp.response
        sz = self.size
        lot = sz.lot_size
        capital = float(req.capital_brl) if req.capital_brl is not None else sz.capital_brl
        d = comp.distribution
        es = d.es if d is not None else None
        max_loss_lot = None
        if d is not None and comp.stress_max_unit is not None:
            max_loss_lot = max(d.es, comp.stress_max_unit * lot)
        mu = None
        if r.direction == "sell" and comp.p_low is not None and comp.cost_sell is not None:
            mu = comp.vega_unit * lot * (comp.p_low - comp.cost_sell)
        elif r.direction == "buy" and comp.p_high is not None and comp.cost_buy is not None:
            mu = comp.vega_unit * lot * (-comp.p_high - comp.cost_buy)
        if r.state != EdgeState.EDGE.value:
            zero_reason = {
                "inconclusive": "semáforo inconclusivo: o intervalo do edge cruza o nível exigido",
                "no_edge": "semáforo sem edge líquido",
                "unavailable": f"semáforo indisponível: {r.reason or 'falta insumo'}",
            }[r.state]
        elif not r.direction_match:
            zero_reason = "a direção da estrutura é oposta à do sinal (RN-SIZ-05)"
        elif d is None:
            zero_reason = f"distribuição simulada indisponível: {r.distribution.reason}"
        else:
            zero_reason = None
        margin = float(req.margin_per_lot_brl) if req.margin_per_lot_brl is not None else None
        common = {
            "kelly_fraction": sz.kelly_fraction,
            "max_loss_fraction": sz.max_loss_fraction,
            "mu_brl": money(mu) if mu is not None else None,
            "variance_brl2": d.variance if d is not None else None,
            "es_brl": money(es) if es is not None else None,
            "stress": comp.stress,
            "stress_notes": comp.stress_notes,
            "max_loss_brl": money(max_loss_lot) if max_loss_lot is not None else None,
            "margin_per_lot_brl": money(margin) if margin is not None else None,
        }
        if capital is None:
            return comp, SizingOut(
                status="unavailable",
                reason="informe o capital alocado para opções (RN-SIZ-01)",
                capital_brl=None,
                kelly_full_lots=None,
                n_kelly=0,
                n_cap=None,
                n_final=0,
                rule="zero",
                margin_total_brl=None,
                margin_share_of_capital=None,
                **common,
            )
        s = size_position(
            SizingInput(
                capital=capital,
                kelly_fraction=sz.kelly_fraction,
                max_loss_fraction=sz.max_loss_fraction,
                mu=mu,
                variance=d.variance if d is not None else None,
                max_loss=max_loss_lot,
                edge_ok=zero_reason is None,
                zero_reason=zero_reason,
            )
        )
        margin_total = margin * s.n_final if margin is not None else None
        return comp, SizingOut(
            status="ok",
            reason=s.reason,
            capital_brl=money(capital),
            kelly_full_lots=s.kelly_full,
            n_kelly=s.n_kelly,
            n_cap=s.n_cap,
            n_final=s.n_final,
            rule=s.rule.value,
            margin_total_brl=money(margin_total) if margin_total is not None else None,
            margin_share_of_capital=margin_total / capital if margin_total is not None else None,
            **common,
        )

    def sizing_response(self, req: SizingRequest) -> SizingResponse:
        comp, out = self.sizing(req)
        # Limites com o capital da configuração (PRD 1.10 §5.9), nunca o do pedido: um capital digitado
        # maior não pode dispensar a justificativa (revisão de segurança da Etapa 7, M-1).
        limits = PortfolioComputer(self.session, user_id=self.user_id).limits(
            self.proforma(comp, req.lots, None)
        )
        return SizingResponse(simulation=comp.response, sizing=out, limits=limits)

    def proforma(self, comp: Computed, lots: int, stock_total: int | None) -> Book:
        """A posição nova como livro de risco (PR-04): pernas × lote × lotes e a ação executada (ou o
        hedge inicial até delta zero, ou a ação da venda coberta)."""
        r = comp.response
        units = self.size.lot_size * lots
        m = comp.market
        legs = [
            RiskLeg(
                position_id=0,
                ticker=r.ticker,
                expiry=r.expiry,
                code=lo.code,
                quantity=leg.quantity * units,
                is_call=leg.is_call,
                strike_eff=leg.strike,
                days_to_expiry_bd=m.days_bd,
                iv=leg.iv,
                rate_c=m.rate_c,
                pv_div=m.pv_dividends(0),
            )
            for leg, lo in zip(comp.legs, r.legs, strict=True)
        ]
        if stock_total is None:
            stock_total = round(initial_hedge(comp.legs, comp.stock_qty, m, comp.dynamic) * units)
        stocks = [RiskStock(0, r.ticker, r.expiry, stock_total)] if stock_total else []
        return Book(legs, stocks, {r.ticker: m.spot})
