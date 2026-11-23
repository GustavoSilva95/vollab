"""Calendário de eventos (PRD §7: GET/POST/PATCH/DELETE /events; RF-EVT-01/02, RS-02).

- Cadastro manual, confirmado ou estimado. Vencimentos de opções vêm das séries (só leitura).
- Ex-dividendo e ex-JCP levam o valor por ação e criam um provento `manual` em
  `corporate_actions` (o manual prevalece sobre Yahoo e ajuste de strike na mesma data). Mudar um
  provento enfileira o recálculo de volatilidade do ativo no worker (RN-VOL-07, RN-PRC-01).
"""

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vollab.analytics.recompute import enqueue_recompute
from vollab.api.schemas.common import ProblemDetails
from vollab.api.schemas.vol import EventCreate, EventOut, EventUpdate, _check_event
from vollab.collection.planner import today_sao_paulo
from vollab.db.models import FIXED_USER_ID, CorporateAction, Event, OptionSeries, Underlying
from vollab.db.models.events import EVENT_KINDS_WITH_AMOUNT
from vollab.db.session import get_session
from vollab.settings import get_settings

router = APIRouter(prefix="/events", tags=["eventos"])
SessionDep = Annotated[Session, Depends(get_session)]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetails, "description": "Evento não encontrado."}
}
CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetails, "description": "Evento duplicado ou provento já cadastrado na data."}
}


def event_out(e: Event) -> EventOut:
    return EventOut(
        id=e.id,
        ticker=e.ticker,
        kind=e.kind,
        event_date=e.event_date,
        status=e.status,
        amount=e.amount,
        note=e.note,
        derived=False,
    )


@router.get("", response_model=list[EventOut], summary="Eventos do usuário e vencimentos de opções")
def list_events(
    session: SessionDep,
    ticker: Annotated[str | None, Query(pattern=r"^[A-Z0-9]{4,12}$")] = None,
    start: Annotated[date | None, Query(description="Padrão: hoje − 180 dias.")] = None,
    end: Annotated[date | None, Query(description="Padrão: hoje + 365 dias.")] = None,
) -> list[EventOut]:
    today = today_sao_paulo(get_settings())
    start = start or today - timedelta(days=180)
    end = end or today + timedelta(days=365)
    stmt = select(Event).where(
        Event.user_id == FIXED_USER_ID, Event.event_date >= start, Event.event_date <= end
    )
    if ticker:
        stmt = stmt.where((Event.ticker == ticker) | Event.ticker.is_(None))
    out = [event_out(e) for e in session.scalars(stmt)]
    # Vencimentos mensais das séries dos ativos cadastrados (RF-EVT-01), derivados do COTAHIST.
    underlyings = session.execute(
        select(Underlying.ticker, Underlying.isin).where(
            Underlying.user_id == FIXED_USER_ID, Underlying.active.is_(True), Underlying.isin.is_not(None)
        )
    ).all()
    for u_ticker, isin in underlyings:
        if ticker and u_ticker != ticker:
            continue
        expiries = session.scalars(
            select(OptionSeries.expiry)
            .where(
                OptionSeries.underlying_isin == isin,
                OptionSeries.is_weekly.is_(False),
                OptionSeries.expiry >= start,
                OptionSeries.expiry <= end,
            )
            .distinct()
        )
        out.extend(
            EventOut(
                id=None,
                ticker=u_ticker,
                kind="expiry",
                event_date=d,
                status="confirmed",
                amount=None,
                note=None,
                derived=True,
            )
            for d in expiries
        )
    return sorted(out, key=lambda e: (e.event_date, e.ticker or "", e.kind))


def _require_underlying(session: Session, ticker: str | None) -> None:
    if ticker is None:
        return
    exists = session.scalar(
        select(Underlying.id).where(Underlying.user_id == FIXED_USER_ID, Underlying.ticker == ticker)
    )
    if exists is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Ativo não cadastrado.")


def _sync_dividend(session: Session, event: Event) -> None:
    """Espelha o evento ex-dividendo/ex-JCP em `corporate_actions` (fonte manual)."""
    action = session.scalar(select(CorporateAction).where(CorporateAction.event_id == event.id))
    if event.kind not in EVENT_KINDS_WITH_AMOUNT or event.ticker is None or event.amount is None:
        if action is not None:
            session.delete(action)
        return
    if action is None:
        action = CorporateAction(event_id=event.id, source="manual")
        session.add(action)
    action.ticker = event.ticker
    action.ex_date = event.event_date
    action.amount = event.amount
    action.kind = "dividend" if event.kind == "ex_dividend" else "jcp"
    action.confirmed = event.status == "confirmed"


def _recompute(session: Session, event: Event) -> None:
    if event.kind in EVENT_KINDS_WITH_AMOUNT and event.ticker:
        enqueue_recompute(
            session,
            user_id=FIXED_USER_ID,
            tickers=[event.ticker],
            full=True,
            skip_intraday=True,
            reason=f"provento {event.id}",
        )


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Já existe um provento manual deste ativo nesta data."
        ) from None


@router.post(
    "",
    response_model=EventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastra um evento",
    responses=CONFLICT,
)
def create_event(body: EventCreate, session: SessionDep) -> EventOut:
    _require_underlying(session, body.ticker)
    event = Event(
        user_id=FIXED_USER_ID,
        ticker=body.ticker,
        kind=body.kind,
        event_date=body.event_date,
        status=body.status,
        amount=body.amount,
        note=body.note,
    )
    session.add(event)
    session.flush()
    _sync_dividend(session, event)
    _recompute(session, event)
    _commit(session)
    session.refresh(event)
    return event_out(event)


def _get(session: Session, event_id: int) -> Event:
    event = session.scalar(select(Event).where(Event.id == event_id, Event.user_id == FIXED_USER_ID))
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evento não encontrado.")
    return event


@router.patch(
    "/{event_id}",
    response_model=EventOut,
    summary="Altera data, situação, valor ou nota",
    responses=NOT_FOUND | CONFLICT,
)
def update_event(event_id: int, body: EventUpdate, session: SessionDep) -> EventOut:
    event = _get(session, event_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(event, field, value)
    try:
        _check_event(event.kind, event.ticker, event.amount)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    session.flush()
    _sync_dividend(session, event)
    _recompute(session, event)
    _commit(session)
    session.refresh(event)
    return event_out(event)


@router.delete(
    "/{event_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga um evento", responses=NOT_FOUND
)
def delete_event(event_id: int, session: SessionDep) -> Response:
    event = _get(session, event_id)
    _recompute(session, event)
    session.delete(event)  # o provento manual ligado cai junto (ON DELETE CASCADE)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
