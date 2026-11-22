"""Coleta sob demanda (PRD §7, ADR-07, RF-DAD-02/05/06)."""

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from vollab.api.schemas.collection import (
    CollectionGapsResponse,
    CollectionPendingResponse,
    CollectionRunResponse,
    GapOut,
    GapSummary,
    GroupCount,
    GroupProgressOut,
    ItemOut,
    ProgressCounts,
    RunSummary,
)
from vollab.api.schemas.common import ProblemDetails
from vollab.collection import report
from vollab.collection.planner import today_sao_paulo
from vollab.collection.runner import ActiveRunError, create_run
from vollab.db.models import FIXED_USER_ID, CollectionItem, CollectionRun
from vollab.db.session import get_session
from vollab.settings import get_settings

router = APIRouter(prefix="/collection", tags=["coleta"])
SessionDep = Annotated[Session, Depends(get_session)]


def _run_summary(run: CollectionRun) -> RunSummary:
    return RunSummary.model_validate(run, from_attributes=True)


def _item(item: CollectionItem) -> ItemOut:
    return ItemOut(
        source=item.source,
        group=report.item_group(item.source, item.phase),
        key=item.key,
        trade_date=item.trade_date,
        underlying=item.underlying,
        status=item.status,
        permanent=item.permanent,
        error=item.error,
    )


def _eta(requests: int) -> int:
    return round(requests / get_settings().http_requests_per_second)


@router.get("/pending", response_model=CollectionPendingResponse, summary="Pregões e itens pendentes")
def get_collection_pending(session: SessionDep) -> CollectionPendingResponse:
    settings = get_settings()
    result = report.pending(session, user_id=FIXED_USER_ID, today=today_sao_paulo(settings))
    active, last = report.latest_runs(session, user_id=FIXED_USER_ID)
    known = len(result.plan.items)
    return CollectionPendingResponse(
        reference_date=result.plan.reference_date,
        intraday_start=result.plan.intraday_days[0],
        bars_start=result.plan.bar_days[0],
        is_initial_load=result.is_initial_load,
        pending_days=result.pending_days,
        counts=[GroupCount(group=g, count=c) for g, c in result.counts.items()],
        known_requests=known,
        days_awaiting_cotahist=len(result.plan.days_without_cotahist),
        estimated_seconds=_eta(known),
        requests_per_second=settings.http_requests_per_second,
        data_source=settings.data_source,
        active_run=_run_summary(active) if active else None,
        last_run=_run_summary(last) if last else None,
    )


@router.post(
    "/runs",
    response_model=CollectionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dispara a coleta (executada pelo worker)",
    responses={409: {"model": ProblemDetails, "description": "Já existe uma coleta em andamento."}},
)
def create_collection_run(session: SessionDep) -> CollectionRunResponse:
    try:
        run = create_run(session, user_id=FIXED_USER_ID)
    except ActiveRunError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma coleta em andamento.") from None
    return _progress(session, run)


def _progress(session: Session, run: CollectionRun) -> CollectionRunResponse:
    prog = report.progress(session, run)
    totals = prog.totals
    return CollectionRunResponse(
        run=_run_summary(run),
        totals=ProgressCounts(**_counts(totals)),
        groups=[GroupProgressOut(group=g.group, **_counts(g)) for g in prog.groups],
        current=_item(prog.current) if prog.current else None,
        estimated_seconds_remaining=_eta(totals.pending) if run.status in ("queued", "running") else 0,
        recent_failures=[_item(i) for i in prog.recent_failures],
    )


def _counts(g: report.GroupProgress) -> dict[str, int]:
    return {"total": g.total, "pending": g.pending, "ok": g.ok, "empty": g.empty, "failed": g.failed}


@router.get(
    "/runs/{run_id}",
    response_model=CollectionRunResponse,
    summary="Progresso de uma coleta",
    responses={404: {"model": ProblemDetails, "description": "Coleta não encontrada."}},
)
def get_collection_run(run_id: int, session: SessionDep) -> CollectionRunResponse:
    run = session.get(CollectionRun, run_id)
    if run is None or run.user_id != FIXED_USER_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Coleta não encontrada.")
    return _progress(session, run)


@router.get("/gaps", response_model=CollectionGapsResponse, summary="Relatório de falhas e lacunas")
def get_collection_gaps(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=2000)] = 300
) -> CollectionGapsResponse:
    rep = report.gaps(session, user_id=FIXED_USER_ID, today=today_sao_paulo(get_settings()))
    summary = Counter(g.kind for g in rep.gaps)
    return CollectionGapsResponse(
        reference_date=rep.reference_date,
        bars_start=rep.bars_start,
        intraday_start=rep.intraday_start,
        summary=[GapSummary(kind=k, count=c) for k, c in sorted(summary.items())],
        gaps=[GapOut.model_validate(g, from_attributes=True) for g in rep.gaps[:limit]],
        gaps_total=len(rep.gaps),
        failures=[_item(i) for i in rep.failures[:limit]],
        failures_total=len(rep.failures),
    )
