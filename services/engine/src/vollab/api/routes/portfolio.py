"""Carteira, stress, limites e cenários de crise (PRD 1.10 §5.9 e §7; BRD 1.7 RF-RSK-01..04, QA-12).

Tudo calculado na leitura a partir das marcações D-1 gravadas; `POST /portfolio/stress` não grava nada.
`POST /risk/crisis/measure` só enfileira o job `crisis_measure` (o download roda no worker).
"""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from vollab.analytics.crisis import JOB_KIND as CRISIS_JOB
from vollab.analytics.crisis import crisis_values, enqueue_crisis
from vollab.analytics.params import risk_params_from_config
from vollab.analytics.portfolio import PortfolioComputer
from vollab.api.schemas.portfolio import (
    CrisisEpisodeOut,
    CrisisMeasureOut,
    CrisisOut,
    CrisisResponse,
    LimitsResponse,
    PortfolioResponse,
    ScenarioOut,
    StressRequest,
)
from vollab.collection.params import ensure_config_version
from vollab.db.models import FIXED_USER_ID, Job, JobStatus, Underlying
from vollab.db.session import get_session

router = APIRouter(tags=["carteira e risco"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "/portfolio", response_model=PortfolioResponse, summary="Greeks agregados e exposição por vencimento"
)
def get_portfolio(session: SessionDep) -> PortfolioResponse:
    return PortfolioComputer(session, user_id=FIXED_USER_ID).view()


@router.post("/portfolio/stress", response_model=ScenarioOut, summary="Stress avulso da carteira (não grava)")
def post_stress(body: StressRequest, session: SessionDep) -> ScenarioOut:
    return PortfolioComputer(session, user_id=FIXED_USER_ID).custom(body.spot_shock, body.vol_shock)


@router.get(
    "/portfolio/limits", response_model=LimitsResponse, summary="Stresses padrão e de crise e limites"
)
def get_limits(session: SessionDep) -> LimitsResponse:
    return PortfolioComputer(session, user_id=FIXED_USER_ID).limits()


@router.get("/risk/crisis", response_model=CrisisResponse, summary="Choques dos cenários de crise (QA-12)")
def get_crisis(session: SessionDep) -> CrisisResponse:
    version = ensure_config_version(session, user_id=FIXED_USER_ID)
    session.commit()
    risk = risk_params_from_config(version)
    tickers = session.scalars(
        select(Underlying.ticker).where(Underlying.user_id == FIXED_USER_ID, Underlying.active.is_(True))
    ).all()
    values = crisis_values(session, risk, tickers, user_id=FIXED_USER_ID)
    job = session.scalars(
        select(Job.status)
        .where(
            Job.kind == CRISIS_JOB,
            Job.user_id == FIXED_USER_ID,
            Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
        .limit(1)
    ).first()
    return CrisisResponse(
        episodes=[
            CrisisEpisodeOut(key=e.key, label=e.label, start=e.start, end=e.end) for e in risk.crisis_episodes
        ],
        horizon_bd=risk.crisis_horizon_bd,
        values=[
            CrisisOut(
                ticker=v.ticker,
                episode=v.episode,
                label=v.label,
                status=cast(Any, v.status),
                origin=cast(Any, v.origin),
                price_shock=v.price_shock,
                vol_shock=v.vol_shock,
                reason=v.reason,
                window_start=v.measurement.window_start if v.measurement else None,
                window_end=v.measurement.window_end if v.measurement else None,
                worst_day=v.measurement.worst_day if v.measurement else None,
                worst_day_return=v.measurement.worst_day_return if v.measurement else None,
                vol_method=cast(Any, v.measurement.vol_method) if v.measurement else None,
                vol_before=v.measurement.vol_before if v.measurement else None,
                vol_after=v.measurement.vol_after if v.measurement else None,
                dividends_checked=v.measurement.dividends_checked if v.measurement else None,
                measured_at=v.measurement.measured_at if v.measurement else None,
            )
            for v in values
        ],
        job=cast(Any, str(job.value) if job is not None else None),
    )


@router.post(
    "/risk/crisis/measure",
    response_model=CrisisMeasureOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Medir os cenários de crise (enfileira o download dos COTAHIST anuais)",
)
def post_crisis_measure(session: SessionDep) -> CrisisMeasureOut:
    job = enqueue_crisis(session, user_id=FIXED_USER_ID, tickers=None, reason="usuário")
    session.commit()
    return CrisisMeasureOut(queued=job is not None, job_id=job.id if job is not None else None)
