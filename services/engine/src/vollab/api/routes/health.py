from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from vollab.api.schemas.health import HealthResponse
from vollab.collection.report import last_collection_at as last_collection_at_of
from vollab.db.session import get_session
from vollab.settings import get_settings

router = APIRouter(tags=["saude"])
log = structlog.get_logger("vollab.api.health")


@router.get("/health", response_model=HealthResponse, summary="Saúde do engine e do banco")
def get_health(session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    last_collection_at = None
    try:
        session.execute(text("SELECT 1"))
        database = "ok"
        last_collection_at = last_collection_at_of(session)
    except SQLAlchemyError:
        log.warning("health.database_unavailable", exc_info=True)
        database = "unavailable"
    settings = get_settings()
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        engine_version=settings.engine_version,
        database=database,
        last_collection_at=last_collection_at,
        data_source=settings.data_source,
    )
