"""Configuração versionada (PRD §5.3 e 1.8 §7; BRD §7.11, RN-EDG-05, RN-CST-02).

`POST /config` valida o snapshot inteiro e grava uma versão nova (nunca altera uma existente).
Parâmetros de custos de leitura e do edge valem na hora no ranking; os de coleta, vol, previsão e
do estimador de spread passam a valer no próximo recálculo (o histórico gravado não é refeito em
silêncio).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from vollab.api.schemas.common import ProblemDetails
from vollab.api.schemas.config import (
    ConfigCreate,
    ConfigCreateOut,
    ConfigParams,
    ConfigVersionOut,
    ConfigVersionSummary,
)
from vollab.collection.params import ensure_config_version
from vollab.db.config_store import create_config_version
from vollab.db.models import FIXED_USER_ID, ConfigVersion
from vollab.db.session import get_session

router = APIRouter(prefix="/config", tags=["configuração"])
SessionDep = Annotated[Session, Depends(get_session)]
MAX_VERSIONS = 200


def _out(version: ConfigVersion) -> ConfigVersionOut:
    return ConfigVersionOut(
        id=version.id,
        created_at=version.created_at,
        note=version.note,
        params=ConfigParams.model_validate(version.params),
    )


@router.get("", response_model=ConfigVersionOut, summary="Configuração vigente")
def get_config(session: SessionDep) -> ConfigVersionOut:
    version = ensure_config_version(session, user_id=FIXED_USER_ID)
    session.commit()
    return _out(version)


@router.post(
    "",
    response_model=ConfigCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar uma versão nova da configuração",
)
def post_config(body: ConfigCreate, session: SessionDep) -> ConfigCreateOut:
    current = ensure_config_version(session, user_id=FIXED_USER_ID)
    params: dict[str, Any] = body.params.model_dump(mode="json")
    if ConfigParams.model_validate(current.params).model_dump(mode="json") == params:
        session.commit()
        return ConfigCreateOut(id=current.id, created=False)
    created = create_config_version(session, user_id=FIXED_USER_ID, params=params, note=body.note)
    session.commit()
    return ConfigCreateOut(id=created.id, created=True)


@router.get("/versions", response_model=list[ConfigVersionSummary], summary="Histórico de versões")
def list_config_versions(session: SessionDep) -> list[ConfigVersionSummary]:
    current = ensure_config_version(session, user_id=FIXED_USER_ID)
    session.commit()
    rows = session.scalars(
        select(ConfigVersion)
        .where(ConfigVersion.user_id == FIXED_USER_ID)
        .order_by(ConfigVersion.id.desc())
        .limit(MAX_VERSIONS)
    ).all()
    return [
        ConfigVersionSummary(id=v.id, created_at=v.created_at, note=v.note, current=v.id == current.id)
        for v in rows
    ]


@router.get(
    "/versions/{version_id}",
    response_model=ConfigVersionOut,
    summary="Uma versão da configuração",
    responses={404: {"model": ProblemDetails, "description": "Versão inexistente."}},
)
def get_config_version(version_id: Annotated[int, Path(ge=1)], session: SessionDep) -> ConfigVersionOut:
    version = session.get(ConfigVersion, version_id)
    if version is None or version.user_id != FIXED_USER_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Versão de configuração inexistente.")
    return _out(version)
