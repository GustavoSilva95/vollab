"""Ranking de oportunidades com semáforo (PRD 1.8 §5.6.1; RF-RNK-01/02, RN-EDG-01..07, RN-CST-01..03).

Calculado na leitura (no máximo 10 ativos; todos os insumos já gravados pelo worker; nenhum negócio
bruto é lido, PRD-NF-06). Endpoint de cálculo: não grava nada.

Por ativo, no pregão da última IV de prazo constante:
1. IV ex-evento (RN-EVT-03), ou o fallback "ATM do vencimento disponível" com o prazo efetivo
   (RN-VOL-05), que deixa tudo `approximate`;
2. σ̂ do modelo escolhido, só se ele tiver avaliação no ativo (RF-PRV-04), com o intervalo da §5.7;
3. spread normal *s* pelas origens do baseline `implied` (QA-14) ou o padrão não calibrado;
4. custos: straddle ATM de referência (spread conservador, taxas e corretagem) e hedge de Leland;
5. prêmio, edge relativo e semáforo nas duas direções; colunas de contexto (IV rank, skew,
   estrutura a termo, eventos e liquidez).
"""

import math
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal, cast

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from vollab.analytics.events import EventContext
from vollab.analytics.forecasting import forecast_interval, vol_from_state
from vollab.analytics.market import DividendInfo, load_dividends, load_holidays, load_rates
from vollab.analytics.params import (
    CostParams,
    EdgeParams,
    ForecastParams,
    VolParams,
    cost_params_from_config,
    edge_params_from_config,
    forecast_params_from_config,
    vol_params_from_config,
)
from vollab.api.schemas.common import EstimatedValue
from vollab.api.schemas.ranking import (
    CostBreakdown,
    LiquidityOut,
    RankingEvent,
    RankingResponse,
    RankingRow,
    TermSlope,
)
from vollab.collection.params import CollectionParams, ensure_config_version, params_from_config
from vollab.collection.planner import today_sao_paulo
from vollab.db.models import (
    AtmTermPoint,
    ConstantMaturityVol,
    DailyBar,
    Event,
    ForecastEvaluation,
    ForecastEvaluationPoint,
    OptionDailyQuote,
    OptionSeries,
    OptionSpreadEstimate,
    RvForecast,
    Underlying,
)
from vollab.quant.calendar import business_days, count_business_days, previous_business_day
from vollab.quant.costs import Band, BandDay, hedge_cost, spread_estimate, straddle_cost
from vollab.quant.edge import EdgeState, classify, iv_rank, normal_spread, premium, ranking_key
from vollab.quant.forecast import Baseline
from vollab.quant.implied import SmilePoint, iv_at_moneyness
from vollab.quant.pricing import BUSINESS_DAYS_PER_YEAR, continuous_rate
from vollab.settings import get_settings

Status = Literal["ok", "insufficient_data", "unavailable"]
Origin = Literal["observed", "estimated", "manual", "approximate"]
_CENT = Decimal("0.01")


def _money(value: float) -> str:
    return str(Decimal(repr(value)).quantize(_CENT, rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True, slots=True)
class _Params:
    vol: VolParams
    forecast: ForecastParams
    costs: CostParams
    edge: EdgeParams
    collection: CollectionParams
    version_id: int


class _Values:
    """Fábrica de `EstimatedValue` com o nível e a data de referência do ranking."""

    def __init__(self, level: float, expected_as_of: date) -> None:
        self.level = level
        self.expected = expected_as_of

    def make(
        self,
        value: float | None,
        as_of: date | None,
        *,
        status: Status = "ok",
        origin: Origin = "estimated",
        reason: str | None = None,
        ci: tuple[float | None, float | None] = (None, None),
        calibrated: bool | None = None,
    ) -> EstimatedValue:
        ok = status == "ok" and value is not None
        day = as_of or self.expected
        return EstimatedValue(
            value=value if ok else None,
            ci_low=ci[0] if ok else None,
            ci_high=ci[1] if ok else None,
            ci_level=self.level,
            status=status if status != "ok" or ok else "unavailable",
            origin=origin,
            as_of=day,
            stale=day < self.expected,
            reason=reason,
            calibrated=calibrated,
        )

    def missing(self, as_of: date | None, reason: str, status: Status = "unavailable") -> EstimatedValue:
        return self.make(None, as_of, status=status, reason=reason)


def _join(*parts: str | None) -> str | None:
    out = "; ".join(p for p in parts if p)
    return out or None


def _nth_business_day_after(day: date, n: int, holidays: frozenset[date]) -> date:
    """O n-ésimo pregão depois de `day` (vencimento sintético do prazo constante)."""
    end = day + timedelta(days=n * 2 + 15)
    days = [d for d in business_days(day + timedelta(days=1), end, holidays)]
    return days[n - 1] if len(days) >= n else end


class RankingComputer:
    def __init__(self, session: Session, *, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id
        version = ensure_config_version(session, user_id=user_id)
        session.commit()
        self.p = _Params(
            vol=vol_params_from_config(version),
            forecast=forecast_params_from_config(version),
            costs=cost_params_from_config(version),
            edge=edge_params_from_config(version),
            collection=params_from_config(version),
            version_id=version.id,
        )
        self.holidays = load_holidays(session)
        self.rates = load_rates(session)
        self.expected_as_of = previous_business_day(today_sao_paulo(get_settings()), self.holidays)
        self.v = _Values(self.p.vol.ci_level, self.expected_as_of)
        self.h = self.p.vol.constant_maturity_bd
        self.eval_h = min(self.p.forecast.evaluation_horizons_bd, key=lambda x: (abs(x - self.h), x))

    def run(self, tickers: list[str] | None = None) -> RankingResponse:
        s = self.session
        stmt = select(Underlying.ticker).where(
            Underlying.user_id == self.user_id, Underlying.active.is_(True)
        )
        found = sorted(s.scalars(stmt))
        chosen = [t for t in found if tickers is None or t in tickers]
        rows = [self.row(t) for t in chosen]
        rows.sort(key=lambda r: ranking_key(EdgeState(r.state), r.net_relative_edge, r.ticker))
        for i, r in enumerate(rows, start=1):
            r.position = i
        return RankingResponse(
            expected_as_of=self.expected_as_of,
            horizon_bd=self.h,
            selected_model=self.p.forecast.selected_model,
            ci_level=self.p.vol.ci_level,
            config_version_id=self.p.version_id,
            engine_version=get_settings().engine_version,
            rows=rows,
        )

    # Linha de um ativo ------------------------------------------------------------------------

    def row(self, ticker: str) -> RankingRow:
        s = self.session
        model = self.p.forecast.selected_model
        cm = s.scalars(
            select(ConstantMaturityVol)
            .where(ConstantMaturityVol.ticker == ticker, ConstantMaturityVol.target_bd == self.h)
            .order_by(ConstantMaturityVol.as_of.desc())
            .limit(1)
        ).first()
        as_of = cm.as_of if cm else None
        empty = self.v.missing(as_of, "sem dado")
        base: dict[str, Any] = {
            "position": 0,
            "ticker": ticker,
            "as_of": as_of,
            "state": "unavailable",
            "direction": None,
            "reason": None,
            "approximate": False,
            "horizon_bd": self.h,
            "model": model,
            "iv": empty,
            "iv_with_events": empty,
            "events_removed": [],
            "forecast": empty,
            "normal_spread": empty,
            "normal_spread_pairs": 0,
            "premium": empty,
            "relative_edge": empty,
            "net_relative_edge": None,
            "net_premium": None,
            "expected_pnl_brl": None,
            "threshold": self._threshold(as_of),
            "required_sell": None,
            "required_buy": None,
            "costs": None,
            "iv_rank": empty,
            "iv_percentile": empty,
            "iv_rank_days": 0,
            "skew": empty,
            "skew_expiry": None,
            "term_slope": TermSlope(value=empty),
            "events": [],
            "liquidity": None,
        }
        if cm is None or as_of is None:
            base["reason"] = "sem IV de prazo constante calculada: rode a coleta"
            return RankingRow(**base)

        ctx = EventContext(s, user_id=self.user_id, ticker=ticker, params=self.p.vol)
        base |= self._context(ticker, as_of, cm)

        # 1. IV (ex-evento) e prazo efetivo.
        approximate = False
        if cm.iv is not None:
            h_used = self.h
            raw_iv: float = cm.iv
            iv_ex, iv_reason, removed = ctx.ex_event_iv(as_of, cm.iv)
        elif cm.fallback_iv is not None and cm.fallback_bd and cm.fallback_expiry:
            approximate = True
            h_used = int(cm.fallback_bd)
            raw_iv = cm.fallback_iv
            iv_ex, iv_reason, removed = ctx.ex_event_atm(as_of, cm.fallback_expiry, h_used, cm.fallback_iv)
        else:
            base["reason"] = cm.reason or "IV de prazo constante indisponível"
            base["iv"] = base["iv_with_events"] = self.v.missing(as_of, base["reason"])
            return RankingRow(**base)
        fallback_note = (
            f"IV ATM do vencimento de {cm.fallback_expiry:%d/%m/%Y} ({h_used} du), sem prazo constante "
            f"({cm.reason})"
            if approximate
            else None
        )
        iv_origin: Origin = "approximate" if approximate else ("estimated" if removed else "observed")
        base["approximate"] = approximate
        base["horizon_bd"] = h_used
        base["events_removed"] = removed
        base["iv_with_events"] = self.v.make(
            raw_iv, as_of, origin="approximate" if approximate else "observed", reason=fallback_note
        )
        if iv_ex is None:
            base["reason"] = _join("IV ex-evento indisponível", iv_reason)
            base["iv"] = self.v.missing(as_of, base["reason"])
            return RankingRow(**base)
        base["iv"] = self.v.make(
            iv_ex,
            as_of,
            origin=iv_origin,
            reason=_join(fallback_note, f"{len(removed)} evento(s) removido(s)" if removed else None),
        )

        # 2. Previsão do modelo escolhido.
        forecast = self._forecast(ticker, as_of, h_used, model, approximate)
        base["forecast"] = forecast
        # 3. Spread normal.
        ns_value, ns_pairs = self._normal_spread(ticker, as_of)
        base["normal_spread"], base["normal_spread_pairs"] = ns_value, ns_pairs
        if forecast.status != "ok" or forecast.value is None:
            base["reason"] = forecast.reason or "sem previsão"
            return RankingRow(**base)
        sigma = forecast.value
        lo, hi = forecast.ci_low or sigma, forecast.ci_high or sigma

        # 4. Custos.
        costs, cost_reason = self._costs(ticker, as_of, h_used, iv_ex, sigma)
        base["costs"] = costs
        s_value = cast(float, ns_value.value)
        p = premium(iv_ex, sigma, lo, hi, s_value)
        derived: Origin = "approximate" if approximate or forecast.origin == "approximate" else "estimated"
        base["premium"] = self.v.make(p.value, as_of, origin=derived, ci=(p.ci_low, p.ci_high))
        base["relative_edge"] = self.v.make(
            p.value / sigma, as_of, origin=derived, ci=(p.ci_low / sigma, p.ci_high / sigma)
        )
        if costs is None:
            base["reason"] = cost_reason
            return RankingRow(**base)

        # 5. Semáforo.
        sig = classify(
            p,
            forecast=sigma,
            cost_sell=costs.total_sell_vol_pts,
            cost_buy=costs.total_buy_vol_pts,
            threshold=self.p.edge.threshold_vol_pts,
        )
        vega_point = Decimal(costs.straddle_vega_brl)
        base |= {
            "state": sig.state.value,
            "direction": sig.direction.value,
            "reason": _join(
                fallback_note,
                "compra de vol inviável: o hedge consome todo o edge"
                if costs.total_buy_vol_pts is None
                else None,
            ),
            "net_relative_edge": sig.net_relative,
            "net_premium": sig.net_premium,
            "expected_pnl_brl": None
            if sig.net_premium is None
            else _money(float(vega_point) * sig.net_premium * 100.0),
            "required_sell": sig.required_sell,
            "required_buy": sig.required_buy,
        }
        return RankingRow(**base)

    # Insumos ---------------------------------------------------------------------------------

    def _threshold(self, as_of: date | None) -> EstimatedValue:
        return self.v.make(
            self.p.edge.threshold_vol_pts,
            as_of,
            origin="manual",
            reason="limiar configurado; calibração por dados na Etapa 9 (RN-EDG-05)",
            calibrated=False,
        )

    def _forecast(self, ticker: str, as_of: date, h: int, model: str, approximate: bool) -> EstimatedValue:
        s = self.session
        ev = s.get(ForecastEvaluation, (ticker, model, self.eval_h))
        min_w = self.p.forecast.min_evaluation_windows
        if ev is None or ev.status != "ok":
            n = ev.n_windows if ev else 0
            return self.v.missing(
                as_of,
                f"modelo do edge sem avaliação suficiente no ativo: {n} de {min_w} janelas a {self.eval_h} "
                "pregões; troque o modelo em Modelos ou aguarde mais histórico",
            )
        stored_h = h if h in self.p.forecast.evaluation_horizons_bd else self.eval_h
        row = s.get(RvForecast, (ticker, as_of, model, stored_h))
        if row is None or row.status != "ok" or row.vol is None:
            return self.v.missing(
                as_of, _join("sem previsão do modelo no pregão da IV", row.reason if row else None) or ""
            )
        vol = row.vol if stored_h == h else vol_from_state(model, row.state, h)
        ci, origin, ci_reason = forecast_interval(
            vol, h, self.p.vol.ci_level, ev, min_windows=min_w, evaluated_h=self.eval_h
        )
        if approximate:
            origin = "approximate"
        return self.v.make(
            vol,
            as_of,
            origin=cast(Origin, origin),
            reason=_join(row.reason, ci_reason),
            ci=(ci.low, ci.high),
        )

    def _normal_spread(self, ticker: str, as_of: date) -> tuple[EstimatedValue, int]:
        s = self.session
        lookback = self.p.edge.normal_spread_lookback_bd
        cutoff = as_of - timedelta(days=int(lookback * 365 / BUSINESS_DAYS_PER_YEAR) + 1)
        points = s.execute(
            select(ForecastEvaluationPoint.forecast, ForecastEvaluationPoint.realized).where(
                ForecastEvaluationPoint.ticker == ticker,
                ForecastEvaluationPoint.model == Baseline.IMPLIED.value,
                ForecastEvaluationPoint.horizon_bd == self.eval_h,
                ForecastEvaluationPoint.origin > cutoff,
                ForecastEvaluationPoint.origin <= as_of,
                ForecastEvaluationPoint.forecast.is_not(None),
                ForecastEvaluationPoint.realized.is_not(None),
            )
        ).all()
        ns = normal_spread(
            [float(p[0] or "nan") for p in points],
            [float(p[1] or "nan") for p in points],
            min_pairs=self.p.forecast.min_evaluation_windows,
            default=self.p.edge.normal_spread_default,
            reps=self.p.forecast.bootstrap_reps,
            level=self.p.vol.ci_level,
        )
        if ns.calibrated:
            value = self.v.make(
                ns.value,
                as_of,
                origin="estimated",
                reason=f"mediana de {ns.n_pairs} janelas não sobrepostas (IV − RV)/RV",
                ci=(ns.ci_low, ns.ci_high),
                calibrated=True,
            )
        else:
            value = self.v.make(
                ns.value,
                as_of,
                origin="manual",
                reason=f"não calibrado: {ns.n_pairs} de {self.p.forecast.min_evaluation_windows} janelas "
                "com IV de prazo constante; vale o valor configurado (QA-14)",
                calibrated=False,
            )
        return value, ns.n_pairs

    def _spread_days(self, ticker: str, as_of: date, band: Band) -> list[BandDay]:
        rows = self.session.execute(
            select(
                OptionSpreadEstimate.n_series,
                OptionSpreadEstimate.n_trades,
                OptionSpreadEstimate.rel_median,
                OptionSpreadEstimate.rel_p75,
                OptionSpreadEstimate.quoted_rel_median,
            )
            .where(
                OptionSpreadEstimate.ticker == ticker,
                OptionSpreadEstimate.band == band.value,
                OptionSpreadEstimate.trade_date <= as_of,
            )
            .order_by(OptionSpreadEstimate.trade_date.desc())
            .limit(self.p.costs.spread_lookback_bd)
        ).all()
        return [BandDay(*r) for r in rows]

    def _costs(
        self, ticker: str, as_of: date, h: int, iv: float, sigma: float
    ) -> tuple[CostBreakdown | None, str | None]:
        c = self.p.costs
        atm = spread_estimate(self._spread_days(ticker, as_of, Band.ATM))
        if atm is None:
            return None, (
                f"sem estimativa de spread das opções ATM nos últimos {c.spread_lookback_bd} pregões "
                f"(séries com ≥ {c.spread_min_trades} negócios)"
            )
        bar = self.session.get(DailyBar, (ticker, as_of))
        rate = self.rates.on(as_of)
        if bar is None or rate is None:
            return None, "sem OHLC oficial ou Selic no pregão da IV"
        spot = float(bar.close)
        und = spread_estimate(self._spread_days(ticker, as_of, Band.UNDERLYING))
        und_spread = und.conservative if und else c.tick_brl / spot
        rate_c = continuous_rate(rate)
        t = h / BUSINESS_DAYS_PER_YEAR
        expiry = _nth_business_day_after(as_of, h, self.holidays)
        pv_div = self._pv_dividends(load_dividends(self.session, ticker), as_of, expiry, rate_c)
        opt = straddle_cost(
            spot=spot,
            t=t,
            rate_c=rate_c,
            iv=iv,
            pv_div=pv_div,
            option_rel_spread=atm.conservative,
            fee_rate=c.option_fee_rate,
            brokerage_rate=c.brokerage_rate,
            brokerage_per_order_brl=c.brokerage_per_order_brl,
            reference_contracts=c.reference_contracts,
        )
        hedge = hedge_cost(
            sigma,
            underlying_rel_spread=und_spread,
            fee_rate=c.underlying_fee_rate,
            interval_bd=c.hedge_interval_bd,
        )
        opt_pts = opt.vol_points
        return (
            CostBreakdown(
                option_spread_central=atm.central,
                option_spread_conservative=atm.conservative,
                option_spread_quoted=atm.quoted,
                underlying_spread=und_spread,
                underlying_spread_estimated=und is not None,
                spread_days=atm.days,
                spread_series=atm.n_series,
                reference_contracts=c.reference_contracts,
                straddle_premium_brl=_money(opt.premium_brl),
                straddle_vega_brl=str(Decimal(repr(opt.vega_brl / 100.0)).quantize(Decimal("0.0001"))),
                spread_brl=_money(opt.spread_brl),
                fees_brl=_money(opt.fees_brl),
                brokerage_brl=_money(opt.brokerage_brl),
                options_vol_pts=opt_pts,
                hedge_sell_vol_pts=hedge.sell,
                hedge_buy_vol_pts=hedge.buy,
                hedge_half_spread=hedge.half_spread,
                hedge_interval_bd=c.hedge_interval_bd,
                total_sell_vol_pts=opt_pts + hedge.sell,
                total_buy_vol_pts=None if hedge.buy is None else opt_pts + hedge.buy,
            ),
            None,
        )

    def _pv_dividends(
        self, dividends: dict[date, DividendInfo], as_of: date, expiry: date, rate_c: float
    ) -> float:
        pv = 0.0
        for ex, info in dividends.items():
            if as_of < ex <= expiry:
                t_ex = count_business_days(as_of, ex, self.holidays) / BUSINESS_DAYS_PER_YEAR
                pv += info.amount * math.exp(-rate_c * t_ex)
        return pv

    # Colunas de contexto (RF-RNK-02) -------------------------------------------------------

    def _context(self, ticker: str, as_of: date, cm: ConstantMaturityVol) -> dict[str, Any]:
        s = self.session
        out: dict[str, Any] = {}
        # IV rank e percentil (com evento), últimos 252 pregões com IV.
        hist = s.scalars(
            select(ConstantMaturityVol.iv)
            .where(
                ConstantMaturityVol.ticker == ticker,
                ConstantMaturityVol.target_bd == self.h,
                ConstantMaturityVol.as_of <= as_of,
                ConstantMaturityVol.iv.is_not(None),
            )
            .order_by(ConstantMaturityVol.as_of.desc())
            .limit(BUSINESS_DAYS_PER_YEAR)
        ).all()
        min_days = self.p.edge.iv_rank_min_days
        label = f"relativo ao último ano ({len(hist)} pregões com IV de prazo constante)"
        if cm.iv is None:
            out["iv_rank"] = out["iv_percentile"] = self.v.missing(
                as_of, "sem IV de prazo constante no pregão"
            )
        else:
            r = iv_rank([float(x) for x in hist if x is not None], cm.iv, min_days=min_days)
            if r.rank is None:
                why = f"{r.n_days} de {min_days} pregões com IV de prazo constante"
                out["iv_rank"] = out["iv_percentile"] = self.v.missing(as_of, why, "insufficient_data")
            else:
                out["iv_rank"] = self.v.make(r.rank, as_of, origin="observed", reason=label)
                out["iv_percentile"] = self.v.make(r.percentile, as_of, origin="observed", reason=label)
        out["iv_rank_days"] = len(hist)

        # Estrutura a termo e skew.
        term = s.scalars(
            select(AtmTermPoint)
            .where(AtmTermPoint.ticker == ticker, AtmTermPoint.as_of == as_of, AtmTermPoint.status == "ok")
            .order_by(AtmTermPoint.expiry)
        ).all()
        if len(term) >= 2:
            t1, t2 = term[0], term[1]
            out["term_slope"] = TermSlope(
                value=self.v.make((t2.atm_iv or 0.0) - (t1.atm_iv or 0.0), as_of, origin="observed"),
                expiry1=t1.expiry,
                expiry2=t2.expiry,
                days1_bd=t1.days_to_expiry_bd,
                days2_bd=t2.days_to_expiry_bd,
            )
        else:
            out["term_slope"] = TermSlope(value=self.v.missing(as_of, "sem dois vencimentos com IV ATM"))
        out["skew"], out["skew_expiry"] = self._skew(ticker, as_of, term)

        # Eventos próximos e liquidez.
        end = _nth_business_day_after(as_of, self.h, self.holidays)
        events = s.scalars(
            select(Event)
            .where(
                Event.user_id == self.user_id,
                or_(Event.ticker == ticker, Event.ticker.is_(None)),
                Event.event_date > as_of,
                Event.event_date <= end,
            )
            .order_by(Event.event_date, Event.id)
        ).all()
        out["events"] = [
            RankingEvent(id=e.id, kind=e.kind, event_date=e.event_date, status=e.status, ticker=e.ticker)
            for e in events
        ]
        out["liquidity"] = self._liquidity(ticker, as_of)
        return out

    def _skew(
        self, ticker: str, as_of: date, term: list[AtmTermPoint] | Any
    ) -> tuple[EstimatedValue, date | None]:
        if not term:
            return self.v.missing(as_of, "sem vencimento com IV ATM"), None
        chosen = min(term, key=lambda p: (abs(p.days_to_expiry_bd - self.h), p.expiry))
        isin = self.session.scalar(select(Underlying.isin).where(Underlying.ticker == ticker).limit(1))
        rows = self.session.execute(
            select(OptionSeries.option_type, OptionDailyQuote.effective_strike, OptionDailyQuote.iv)
            .join(OptionDailyQuote, OptionDailyQuote.series_id == OptionSeries.id)
            .where(
                OptionSeries.underlying_isin == isin,
                OptionSeries.expiry == chosen.expiry,
                OptionDailyQuote.trade_date == as_of,
                OptionDailyQuote.liquid.is_(True),
                OptionDailyQuote.iv.is_not(None),
            )
        ).all()
        points = [SmilePoint(float(k), float(iv), kind == "call") for kind, k, iv in rows if iv is not None]
        liq = self.p.collection.liquidity
        k_min, k_max = float(liq.moneyness_min), float(liq.moneyness_max)
        lo_kf, hi_kf = self.p.edge.skew_moneyness
        low = iv_at_moneyness(points, chosen.forward, lo_kf, k_min=k_min, k_max=k_max)
        high = iv_at_moneyness(points, chosen.forward, hi_kf, k_min=k_min, k_max=k_max)
        if low.iv is None or high.iv is None:
            return self.v.missing(as_of, low.reason or high.reason or "smile incompleto"), chosen.expiry
        return (
            self.v.make(
                low.iv - high.iv,
                as_of,
                origin="observed",
                reason=f"IV(K/F {lo_kf:g}) − IV(K/F {hi_kf:g}), vencimento de {chosen.expiry:%d/%m/%Y}",
            ),
            chosen.expiry,
        )

    def _liquidity(self, ticker: str, as_of: date) -> LiquidityOut | None:
        liq = self.p.collection.liquidity
        row = self.session.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE st.trades_count >= :min_trades
                                          AND (:weeklies OR NOT s.is_weekly)),
                       coalesce(sum(st.trades_count), 0),
                       coalesce(sum(st.volume), 0)
                FROM option_daily_stats st
                JOIN option_series s ON s.id = st.series_id
                JOIN underlyings u ON u.isin = s.underlying_isin AND u.ticker = :t AND u.user_id = :uid
                WHERE st.trade_date = :d AND s.expiry >= :d
                """
            ),
            {
                "min_trades": liq.min_trades,
                "weeklies": liq.include_weeklies,
                "t": ticker,
                "uid": self.user_id,
                "d": as_of,
            },
        ).one()
        if not row[1]:
            return None
        return LiquidityOut(
            liquid_series=int(row[0]),
            option_trades=int(row[1]),
            option_volume_brl=str(Decimal(row[2]).quantize(_CENT)),
        )
