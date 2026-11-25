"""Alertas de gestão da operação (PRD 1.11 §5.10 e §7; BRD 1.8 RN-GES-01..07, PRD-UI-10).

`GET /alerts` lê o que o job `alerts_evaluate` gravou (nenhuma regra é avaliada na leitura).
`PATCH /alerts/{id}` é a única escrita do usuário: marcar como visto ou resolver (com nota).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from vollab.analytics.alerts_view import alert_out, list_alerts
from vollab.analytics.management import AlertTransitionError, transition
from vollab.api.schemas.alerts import AlertKind, AlertOut, AlertPatch, AlertsResponse
from vollab.api.schemas.common import ProblemDetails
from vollab.db.models import FIXED_USER_ID, Alert, Position
from vollab.db.session import get_session

router = APIRouter(prefix="/alerts", tags=["alertas"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=AlertsResponse, summary="Alertas (padrão: não resolvidos)")
def get_alerts(
    session: SessionDep,
    state: Annotated[
        Literal["open", "active", "seen", "resolved", "all"],
        Query(description="`open` = ativos e vistos (padrão)."),
    ] = "open",
    position_id: Annotated[int | None, Query(ge=1)] = None,
    kind: Annotated[AlertKind | None, Query()] = None,
) -> AlertsResponse:
    return list_alerts(session, user_id=FIXED_USER_ID, state=state, position_id=position_id, kind=kind)


@router.patch(
    "/{alert_id}",
    response_model=AlertOut,
    summary="Marcar como visto ou resolver",
    responses={
        404: {"model": ProblemDetails, "description": "Alerta inexistente."},
        409: {"model": ProblemDetails, "description": "Alerta já resolvido."},
        422: {"model": ProblemDetails, "description": "Transição inválida."},
    },
)
def patch_alert(alert_id: Annotated[int, Path(ge=1)], body: AlertPatch, session: SessionDep) -> AlertOut:
    alert = session.get(Alert, alert_id, with_for_update=True)
    if alert is None or alert.user_id != FIXED_USER_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerta inexistente.")
    try:
        transition(alert, body.state, body.note)
    except AlertTransitionError as exc:
        session.rollback()
        code = status.HTTP_409_CONFLICT if exc.conflict else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(code, str(exc)) from None
    session.commit()
    pos: dict[int, tuple[str, str]] = {}
    if alert.position_id is not None:
        p = session.get(Position, alert.position_id)
        if p is not None:
            pos[p.id] = (p.ticker, p.structure)
    return alert_out(alert, pos)
