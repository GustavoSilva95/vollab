"""Ranking com semáforo e spreads estimados (PRD 1.8 §5.6.1 e §7; RF-RNK-01/02, RN-CST-03).

Calculado na leitura; não grava nada.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from vollab.analytics.params import cost_params_from_config
from vollab.analytics.ranking import RankingComputer
from vollab.api.schemas.common import ProblemDetails
from vollab.api.schemas.ranking import RankingResponse, SpreadDayOut, SpreadsResponse
from vollab.collection.params import ensure_config_version
from vollab.db.models import FIXED_USER_ID, OptionSpreadEstimate, Underlying
from vollab.db.session import get_session

router = APIRouter(tags=["ranking"])
SessionDep = Annotated[Session, Depends(get_session)]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetails, "description": "Ativo não cadastrado."}
}


@router.get("/ranking", response_model=RankingResponse, summary="Ranking dos ativos com semáforo de edge")
def get_ranking(
    session: SessionDep,
    underlying: Annotated[
        str | None, Query(min_length=1, max_length=12, description="Só um ativo (detalhe).")
    ] = None,
) -> RankingResponse:
    computer = RankingComputer(session, user_id=FIXED_USER_ID)
    return computer.run([underlying.upper()] if underlying else None)


@router.get(
    "/underlyings/{ticker}/spreads",
    response_model=SpreadsResponse,
    summary="Spread estimado por faixa de moneyness",
    responses=NOT_FOUND,
)
def get_spreads(
    ticker: str,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=252, description="Pregões mais recentes.")] = 21,
) -> SpreadsResponse:
    ticker = ticker.upper()
    found = session.scalar(
        select(Underlying.ticker).where(Underlying.user_id == FIXED_USER_ID, Underlying.ticker == ticker)
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ativo não cadastrado.")
    version = ensure_config_version(session, user_id=FIXED_USER_ID)
    session.commit()
    costs = cost_params_from_config(version)
    dates = session.scalars(
        select(OptionSpreadEstimate.trade_date)
        .where(OptionSpreadEstimate.ticker == ticker)
        .distinct()
        .order_by(OptionSpreadEstimate.trade_date.desc())
        .limit(days)
    ).all()
    rows = (
        session.scalars(
            select(OptionSpreadEstimate)
            .where(OptionSpreadEstimate.ticker == ticker, OptionSpreadEstimate.trade_date.in_(dates))
            .order_by(OptionSpreadEstimate.trade_date, OptionSpreadEstimate.band)
        ).all()
        if dates
        else []
    )
    return SpreadsResponse(
        ticker=ticker,
        moneyness_bands=costs.moneyness_bands,
        lookback_bd=costs.spread_lookback_bd,
        days=[
            SpreadDayOut(
                trade_date=r.trade_date,
                band=r.band,
                n_series=r.n_series,
                n_trades=r.n_trades,
                rel_median=r.rel_median,
                rel_p75=r.rel_p75,
                quoted_rel_median=r.quoted_rel_median,
            )
            for r in rows
        ],
    )
