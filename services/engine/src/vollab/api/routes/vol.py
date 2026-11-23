"""Séries, volatilidade realizada e implícita de um ativo (PRD §7; RF-VOL-01..05, RN-EVT-01..03).

Só leitura de agregados calculados no worker (PRD-NF-06): nenhuma rota lê negócios brutos.
"""

from collections import defaultdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vollab.analytics.events import EventContext
from vollab.analytics.market import load_dividends, load_holidays
from vollab.analytics.params import VolParams, vol_params_from_config
from vollab.api.routes.events import event_out
from vollab.api.schemas.common import EstimatedValue, ProblemDetails
from vollab.api.schemas.vol import (
    ConstantMaturityOut,
    ConstantMaturityResponse,
    EstimatorSeries,
    EventJumpOut,
    EventJumpsResponse,
    IntradayQuality,
    IvQuality,
    PriceHistory,
    PricePoint,
    RealizedPoint,
    RealizedVolResponse,
    SeriesOut,
    SeriesResponse,
    SmilePointOut,
    SmileResponse,
    TermPointOut,
    TermStructureResponse,
    UnderlyingSummary,
)
from vollab.collection.params import ensure_config_version, params_from_config
from vollab.collection.planner import today_sao_paulo
from vollab.db.models import (
    FIXED_USER_ID,
    AtmTermPoint,
    DailyBar,
    Event,
    IntradaySession,
    OptionDailyQuote,
    OptionDailyStat,
    OptionSeries,
    RealizedVol,
    Underlying,
)
from vollab.db.session import get_session
from vollab.quant.calendar import business_days, count_business_days, previous_business_day
from vollab.quant.vol import Estimator
from vollab.settings import get_settings

router = APIRouter(prefix="/underlyings/{ticker}", tags=["volatilidade"])
SessionDep = Annotated[Session, Depends(get_session)]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetails, "description": "Ativo não cadastrado."}
}

REALIZED_REASONS = {
    "missing_days": "pregões ausentes ou inválidos na janela",
    "incomplete_sessions": "pregões intradiários incompletos na janela (cobertura abaixo do mínimo)",
    "non_positive": "variância estimada não positiva",
}


class _Ctx:
    def __init__(self, session: Session, ticker: str) -> None:
        underlying = session.scalar(
            select(Underlying).where(Underlying.user_id == FIXED_USER_ID, Underlying.ticker == ticker)
        )
        if underlying is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ativo não cadastrado.")
        self.session = session
        self.ticker = ticker
        self.isin = underlying.isin
        version = ensure_config_version(session, user_id=FIXED_USER_ID)
        session.commit()
        self.params: VolParams = vol_params_from_config(version)
        self.liquidity = params_from_config(version).liquidity
        self.holidays = load_holidays(session)
        self.expected_as_of = previous_business_day(today_sao_paulo(get_settings()), self.holidays)

    def stale(self, as_of: date) -> bool:
        return as_of < self.expected_as_of

    def estimated(
        self,
        value: float | None,
        as_of: date,
        *,
        reason: str | None = None,
        status_: str | None = None,
        origin: str = "estimated",
        ci: tuple[float | None, float | None] = (None, None),
    ) -> EstimatedValue:
        st = status_ or ("ok" if value is not None else "insufficient_data")
        return EstimatedValue(
            value=value if st == "ok" else None,
            ci_low=ci[0],
            ci_high=ci[1],
            ci_level=self.params.ci_level,
            status=st,
            origin=origin,
            as_of=as_of,
            stale=self.stale(as_of),
            reason=reason,
        )

    def latest_quote_date(self) -> date | None:
        if self.isin is None:
            return None
        return self.session.scalar(
            select(func.max(OptionDailyQuote.trade_date))
            .join(OptionSeries, OptionSeries.id == OptionDailyQuote.series_id)
            .where(OptionSeries.underlying_isin == self.isin)
        )


def _ctx(ticker: str, session: SessionDep) -> _Ctx:
    return _Ctx(session, ticker.upper())


CtxDep = Annotated[_Ctx, Depends(_ctx)]


# --- Resumo e preços -------------------------------------------------------------------------


@router.get("/summary", response_model=UnderlyingSummary, summary="Resumo do ativo", responses=NOT_FOUND)
def get_underlying_summary(ctx: CtxDep) -> UnderlyingSummary:
    s = ctx.session
    bar = s.scalars(
        select(DailyBar).where(DailyBar.ticker == ctx.ticker).order_by(DailyBar.trade_date.desc()).limit(1)
    ).first()
    session_row = s.scalars(
        select(IntradaySession)
        .where(IntradaySession.ticker == ctx.ticker)
        .order_by(IntradaySession.trade_date.desc())
        .limit(1)
    ).first()
    iv_quality = None
    qdate = ctx.latest_quote_date()
    if qdate is not None and ctx.isin is not None:
        row = s.execute(
            select(
                func.sum(OptionDailyQuote.trades_valid),
                func.sum(OptionDailyQuote.trades_synced),
                func.sum(OptionDailyQuote.trades_lag_discarded),
                func.sum(OptionDailyQuote.trades_no_solution),
            )
            .join(OptionSeries, OptionSeries.id == OptionDailyQuote.series_id)
            .where(OptionSeries.underlying_isin == ctx.isin, OptionDailyQuote.trade_date == qdate)
        ).one()
        iv_quality = IvQuality(
            trade_date=qdate,
            trades_valid=int(row[0] or 0),
            trades_synced=int(row[1] or 0),
            trades_lag_discarded=int(row[2] or 0),
            trades_no_solution=int(row[3] or 0),
            sync_window_s=ctx.params.implied.sync_window_s,
        )
    computed_at = s.scalar(
        select(func.max(IntradaySession.computed_at)).where(IntradaySession.ticker == ctx.ticker)
    )
    return UnderlyingSummary(
        ticker=ctx.ticker,
        isin=ctx.isin,
        as_of=bar.trade_date if bar else None,
        close=bar.close if bar else None,
        expected_as_of=ctx.expected_as_of,
        intraday=IntradayQuality(
            trade_date=session_row.trade_date,
            bars_total=session_row.bars_total,
            bars_with_trades=session_row.bars_with_trades,
            coverage=session_row.coverage,
            complete=session_row.complete,
        )
        if session_row
        else None,
        iv_quality=iv_quality,
        computed_at=computed_at,
    )


@router.get("/prices", response_model=PriceHistory, summary="OHLC oficial diário", responses=NOT_FOUND)
def get_price_history(
    ctx: CtxDep, days: Annotated[int, Query(ge=5, le=1260, description="Pregões a devolver.")] = 252
) -> PriceHistory:
    rows = ctx.session.scalars(
        select(DailyBar).where(DailyBar.ticker == ctx.ticker).order_by(DailyBar.trade_date.desc()).limit(days)
    ).all()
    rows = list(reversed(rows))
    dividends = load_dividends(ctx.session, ctx.ticker)
    calendar = list(business_days(rows[0].trade_date, rows[-1].trade_date, ctx.holidays)) if rows else []
    return PriceHistory(
        ticker=ctx.ticker,
        points=[
            PricePoint(
                trade_date=r.trade_date,
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                dividend=dividends[r.trade_date].amount if r.trade_date in dividends else None,
            )
            for r in rows
        ],
        calendar=calendar,
    )


# --- Séries ----------------------------------------------------------------------------------


@router.get(
    "/series", response_model=SeriesResponse, summary="Séries de opção do pregão", responses=NOT_FOUND
)
def get_underlying_series(
    ctx: CtxDep,
    trade_date: Annotated[date | None, Query(alias="date", description="Padrão: o último.")] = None,
) -> SeriesResponse:
    s = ctx.session
    if ctx.isin is None:
        return SeriesResponse(ticker=ctx.ticker, as_of=None, series=[])
    day = trade_date or s.scalar(
        select(func.max(OptionDailyStat.trade_date))
        .join(OptionSeries, OptionSeries.id == OptionDailyStat.series_id)
        .where(OptionSeries.underlying_isin == ctx.isin)
    )
    if day is None:
        return SeriesResponse(ticker=ctx.ticker, as_of=None, series=[])
    rows = s.execute(
        select(OptionSeries, OptionDailyStat, OptionDailyQuote)
        .join(OptionDailyStat, OptionDailyStat.series_id == OptionSeries.id)
        .outerjoin(
            OptionDailyQuote,
            (OptionDailyQuote.series_id == OptionSeries.id) & (OptionDailyQuote.trade_date == day),
        )
        .where(
            OptionSeries.underlying_isin == ctx.isin,
            OptionDailyStat.trade_date == day,
            OptionSeries.expiry > day,
        )
        .order_by(OptionSeries.expiry, OptionSeries.option_type, OptionDailyStat.strike)
    ).all()
    liquidity = ctx.liquidity
    out = []
    for series, stat, quote in rows:
        iv = None
        if quote is not None:
            iv = ctx.estimated(
                quote.iv,
                day,
                status_="ok" if quote.iv is not None else "unavailable",
                reason="baixa amostra: IV do último negócio sincronizado"
                if quote.status == "low_sample"
                else None,
            )
        out.append(
            SeriesOut(
                code=series.code,
                expiry=series.expiry,
                option_type=series.option_type,
                style=series.style,
                is_weekly=series.is_weekly,
                strike=stat.strike,
                effective_strike=quote.effective_strike if quote else None,
                days_to_expiry_bd=count_business_days(day, series.expiry, ctx.holidays),
                trades_count=stat.trades_count,
                liquid=quote.liquid
                if quote
                else stat.trades_count >= liquidity.min_trades
                and (liquidity.include_weeklies or not series.is_weekly),
                iv=iv,
                iv_status=quote.status if quote else None,
                trades_used=quote.trades_used if quote else None,
            )
        )
    return SeriesResponse(ticker=ctx.ticker, as_of=day, series=out)


# --- RV --------------------------------------------------------------------------------------


@router.get(
    "/vol/realized",
    response_model=RealizedVolResponse,
    summary="RV por estimador e janela",
    responses=NOT_FOUND,
)
def get_realized_vol(
    ctx: CtxDep,
    window_bd: Annotated[
        int | None, Query(ge=2, le=252, description="Padrão: todas as configuradas.")
    ] = None,
    days: Annotated[int, Query(ge=5, le=1260, description="Pregões de histórico.")] = 252,
) -> RealizedVolResponse:
    s = ctx.session
    windows = [window_bd] if window_bd else ctx.params.windows_bd
    last = s.scalar(select(func.max(RealizedVol.as_of)).where(RealizedVol.ticker == ctx.ticker))
    estimators: list[EstimatorSeries] = []
    if last is not None:
        start = s.scalar(
            select(DailyBar.trade_date)
            .where(DailyBar.ticker == ctx.ticker)
            .order_by(DailyBar.trade_date.desc())
            .offset(days - 1)
            .limit(1)
        )
        stmt = select(RealizedVol).where(RealizedVol.ticker == ctx.ticker, RealizedVol.window_bd.in_(windows))
        if start is not None:
            stmt = stmt.where(RealizedVol.as_of >= start)
        grouped: dict[tuple[str, int], list[RealizedVol]] = defaultdict(list)
        for row in s.scalars(stmt.order_by(RealizedVol.as_of)):
            grouped[(row.estimator, row.window_bd)].append(row)
        for window in windows:
            for est in Estimator:
                rows = grouped.get((est.value, window))
                if not rows:
                    continue
                latest = rows[-1]
                estimators.append(
                    EstimatorSeries(
                        estimator=est.value,
                        window_bd=window,
                        latest=ctx.estimated(
                            latest.vol,
                            latest.as_of,
                            reason=REALIZED_REASONS.get(latest.reason or ""),
                        ),
                        points=[
                            RealizedPoint(
                                as_of=r.as_of,
                                vol=r.vol,
                                variance_annual=r.variance_annual,
                                status=r.status,
                                reason=REALIZED_REASONS.get(r.reason or ""),
                                missing_days=r.missing_days,
                            )
                            for r in rows
                        ],
                    )
                )
    official = (
        "close_to_close" if ctx.params.close_to_close_mode == "zero_mean" else "close_to_close_demeaned"
    )
    return RealizedVolResponse(
        ticker=ctx.ticker,
        windows_bd=windows,
        official_close_to_close=official,
        estimators=estimators,
    )


# --- IV --------------------------------------------------------------------------------------


@router.get(
    "/vol/implied/smile", response_model=SmileResponse, summary="Smile por vencimento", responses=NOT_FOUND
)
def get_smile(
    ctx: CtxDep,
    expiry: Annotated[date | None, Query(description="Padrão: o 1º vencimento com IV.")] = None,
    trade_date: Annotated[date | None, Query(alias="date", description="Padrão: o último.")] = None,
) -> SmileResponse:
    s = ctx.session
    day = trade_date or ctx.latest_quote_date()
    empty = SmileResponse(
        ticker=ctx.ticker,
        as_of=day,
        expiries=[],
        expiry=None,
        days_to_expiry_bd=None,
        forward=None,
        atm_iv=None,
        points=[],
    )
    if day is None or ctx.isin is None:
        return empty
    rows = s.execute(
        select(OptionSeries, OptionDailyQuote)
        .join(OptionDailyQuote, OptionDailyQuote.series_id == OptionSeries.id)
        .where(
            OptionSeries.underlying_isin == ctx.isin,
            OptionDailyQuote.trade_date == day,
            OptionDailyQuote.liquid.is_(True),
            OptionDailyQuote.iv.is_not(None),
        )
        .order_by(OptionSeries.expiry, OptionDailyQuote.effective_strike)
    ).all()
    expiries = sorted({r[0].expiry for r in rows})
    if not expiries:
        return empty
    chosen = expiry if expiry in expiries else expiries[0]
    atm = s.get(AtmTermPoint, (ctx.ticker, day, chosen))
    forward = atm.forward if atm else None
    points = []
    for series, quote in rows:
        if series.expiry != chosen or forward is None:
            continue  # sem forward (recálculo pendente) não há moneyness: a tela mostra só os vencimentos
        k = float(quote.effective_strike)
        points.append(
            SmilePointOut(
                code=series.code,
                option_type=series.option_type,
                strike=quote.strike,
                effective_strike=quote.effective_strike,
                moneyness=k / forward,
                iv=float(quote.iv or 0.0),
                status=quote.status,
                trades_used=quote.trades_used,
                out_of_the_money=k >= forward if series.option_type == "call" else k <= forward,
            )
        )
    return SmileResponse(
        ticker=ctx.ticker,
        as_of=day,
        expiries=expiries,
        expiry=chosen,
        days_to_expiry_bd=atm.days_to_expiry_bd if atm else count_business_days(day, chosen, ctx.holidays),
        forward=forward,
        atm_iv=ctx.estimated(
            atm.atm_iv, day, status_="ok" if atm.atm_iv is not None else "unavailable", reason=atm.reason
        )
        if atm
        else None,
        points=points,
    )


@router.get(
    "/vol/term-structure",
    response_model=TermStructureResponse,
    summary="Estrutura a termo da IV ATM",
    responses=NOT_FOUND,
)
def get_term_structure(
    ctx: CtxDep,
    trade_date: Annotated[date | None, Query(alias="date", description="Padrão: o último.")] = None,
) -> TermStructureResponse:
    s = ctx.session
    day = trade_date or s.scalar(
        select(func.max(AtmTermPoint.as_of)).where(AtmTermPoint.ticker == ctx.ticker)
    )
    if day is None:
        return TermStructureResponse(ticker=ctx.ticker, as_of=None, points=[])
    rows = s.scalars(
        select(AtmTermPoint)
        .where(AtmTermPoint.ticker == ctx.ticker, AtmTermPoint.as_of == day)
        .order_by(AtmTermPoint.expiry)
    ).all()
    return TermStructureResponse(
        ticker=ctx.ticker,
        as_of=day,
        points=[
            TermPointOut(
                expiry=r.expiry,
                days_to_expiry_bd=r.days_to_expiry_bd,
                is_weekly=r.is_weekly,
                atm_iv=ctx.estimated(
                    r.atm_iv, day, status_="ok" if r.atm_iv is not None else "unavailable", reason=r.reason
                ),
            )
            for r in rows
        ],
    )


@router.get(
    "/vol/constant-maturity",
    response_model=ConstantMaturityResponse,
    summary="IV ATM de prazo constante, com e sem salto de eventos",
    responses=NOT_FOUND,
)
def get_constant_maturity(
    ctx: CtxDep, days: Annotated[int, Query(ge=5, le=1260, description="Pregões de histórico.")] = 252
) -> ConstantMaturityResponse:
    events = EventContext(ctx.session, user_id=FIXED_USER_ID, ticker=ctx.ticker, params=ctx.params)
    history = []
    for p in events.constant_maturity_history(days):
        unavailable = "unavailable"
        history.append(
            ConstantMaturityOut(
                as_of=p.as_of,
                iv=ctx.estimated(
                    p.iv, p.as_of, status_="ok" if p.iv is not None else unavailable, reason=p.iv_reason
                ),
                iv_ex_event=ctx.estimated(
                    p.iv_ex_event,
                    p.as_of,
                    status_="ok" if p.iv_ex_event is not None else unavailable,
                    reason=p.ex_event_reason,
                ),
                events_removed=p.events_removed,
                fallback_expiry=p.fallback_expiry,
                fallback_bd=p.fallback_bd,
                fallback_iv=p.fallback_iv,
                lower_expiry=p.lower_expiry,
                upper_expiry=p.upper_expiry,
            )
        )
    return ConstantMaturityResponse(
        ticker=ctx.ticker,
        target_bd=ctx.params.constant_maturity_bd,
        latest=history[-1] if history else None,
        history=history,
    )


@router.get(
    "/event-jumps",
    response_model=EventJumpsResponse,
    summary="Salto dos eventos futuros",
    responses=NOT_FOUND,
)
def get_event_jumps(ctx: CtxDep) -> EventJumpsResponse:
    events = EventContext(ctx.session, user_id=FIXED_USER_ID, ticker=ctx.ticker, params=ctx.params)
    as_of = max(events.term) if events.term else None
    if as_of is None:
        last_bar = ctx.session.scalar(
            select(func.max(DailyBar.trade_date)).where(DailyBar.ticker == ctx.ticker)
        )
        as_of = last_bar
    if as_of is None:
        return EventJumpsResponse(ticker=ctx.ticker, as_of=None, jumps=[])
    by_id = {e.id: e for e in events.events}
    out = []
    for j in events.jumps(as_of):
        event: Event = by_id[j.event_id]
        out.append(
            EventJumpOut(
                event=event_out(event),
                as_of=as_of,
                jump=ctx.estimated(
                    j.value,
                    as_of,
                    status_="ok" if j.value is not None else "unavailable",
                    origin=j.origin,
                    reason=j.reason,
                    ci=(j.ci_low, j.ci_high),
                ),
                expected_move=j.expected_move,
                term_structure_value=j.ts_value,
                term_structure_reason=j.ts_reason,
                expiry1=j.expiry1,
                expiry2=j.expiry2,
                historical_value=j.hist_value,
                historical_ci_low=j.hist_ci_low,
                historical_ci_high=j.hist_ci_high,
                historical_n=j.hist_n,
            )
        )
    return EventJumpsResponse(ticker=ctx.ticker, as_of=as_of, jumps=out)
