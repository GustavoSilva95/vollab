"""Lançamentos do diário (PRD 1.10 §5.9 e §7; BRD 1.7 RF-DIA-02/03, RS-06).

`POST /positions/{id}/entries` recebe só insumos; o engine valida pela reexecução do livro (422 com o
motivo) e grava o lançamento imutável. A marcação e a atribuição são refeitas no worker.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vollab.analytics.journal import add_entry, position_view
from vollab.api.schemas.common import ProblemDetails
from vollab.api.schemas.journal import EntryCreate
from vollab.api.schemas.simulation import PositionOut
from vollab.collection.params import ensure_config_version
from vollab.db.models import FIXED_USER_ID, Position
from vollab.db.session import get_session
from vollab.quant.journal import LedgerError

router = APIRouter(tags=["diário"])
SessionDep = Annotated[Session, Depends(get_session)]
ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetails, "description": "Operação inexistente."},
    422: {"model": ProblemDetails, "description": "Lançamento inconsistente (RS-06), com o motivo."},
}


@router.post(
    "/positions/{position_id}/entries",
    response_model=PositionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Lançar hedge, saída, exercício, designação, ajuste de strike ou estorno",
    responses=ERRORS,
)
def post_entry(
    position_id: Annotated[int, Path(ge=1)], body: EntryCreate, session: SessionDep
) -> PositionOut:
    p = session.get(Position, position_id)
    if p is None or p.user_id != FIXED_USER_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Operação inexistente.")
    version = ensure_config_version(session, user_id=FIXED_USER_ID)
    try:
        add_entry(session, p, body, version_id=version.id)
        session.flush()
    except LedgerError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except IntegrityError:
        # Estorno duplo concorrente: o índice único parcial barra o segundo.
        session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Este lançamento já foi estornado."
        ) from None
    session.commit()
    return position_view(session, p)
