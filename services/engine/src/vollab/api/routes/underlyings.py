"""Ativos-objeto do usuário (PRD §7: /underlyings, BRD §5.1: até 10 ativos ativos)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vollab.api.schemas.collection import UnderlyingCreate, UnderlyingOut, UnderlyingUpdate
from vollab.api.schemas.common import ProblemDetails
from vollab.db.models import FIXED_USER_ID, Underlying
from vollab.db.session import get_session

router = APIRouter(prefix="/underlyings", tags=["ativos"])
SessionDep = Annotated[Session, Depends(get_session)]
MAX_ACTIVE = 10


def _active_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Underlying)
            .where(Underlying.user_id == FIXED_USER_ID, Underlying.active.is_(True))
        )
        or 0
    )


def _out(u: Underlying) -> UnderlyingOut:
    return UnderlyingOut(ticker=u.ticker, isin=u.isin, active=u.active)


@router.get("", response_model=list[UnderlyingOut], summary="Ativos cadastrados")
def list_underlyings(session: SessionDep) -> list[UnderlyingOut]:
    rows = session.scalars(
        select(Underlying).where(Underlying.user_id == FIXED_USER_ID).order_by(Underlying.ticker)
    ).all()
    return [_out(u) for u in rows]


@router.post(
    "",
    response_model=UnderlyingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastra um ativo (o ISIN vem do COTAHIST na próxima coleta)",
    responses={409: {"model": ProblemDetails, "description": "Ativo já cadastrado ou limite de 10 ativos."}},
)
def create_underlying(body: UnderlyingCreate, session: SessionDep) -> UnderlyingOut:
    exists = session.scalar(
        select(Underlying).where(Underlying.user_id == FIXED_USER_ID, Underlying.ticker == body.ticker)
    )
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ativo já cadastrado.")
    if _active_count(session) >= MAX_ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Limite de {MAX_ACTIVE} ativos ativos (BRD §5.1).")
    underlying = Underlying(user_id=FIXED_USER_ID, ticker=body.ticker, active=True)
    session.add(underlying)
    session.commit()
    return _out(underlying)


@router.patch(
    "/{ticker}",
    response_model=UnderlyingOut,
    summary="Ativa ou desativa um ativo",
    responses={
        404: {"model": ProblemDetails, "description": "Ativo não encontrado."},
        409: {"model": ProblemDetails, "description": "Limite de ativos."},
    },
)
def update_underlying(ticker: str, body: UnderlyingUpdate, session: SessionDep) -> UnderlyingOut:
    underlying = session.scalar(
        select(Underlying).where(Underlying.user_id == FIXED_USER_ID, Underlying.ticker == ticker)
    )
    if underlying is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ativo não encontrado.")
    if body.active and not underlying.active and _active_count(session) >= MAX_ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Limite de {MAX_ACTIVE} ativos ativos (BRD §5.1).")
    underlying.active = body.active
    session.commit()
    return _out(underlying)
