"""Acesso à configuração versionada (PRD §5.3). Só cria e lê; nunca altera."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from vollab.db.models import ConfigVersion


def create_config_version(
    session: Session, *, user_id: uuid.UUID, params: dict[str, Any], note: str | None = None
) -> ConfigVersion:
    version = ConfigVersion(user_id=user_id, params=params, note=note)
    session.add(version)
    session.flush()
    return version


def current_config_version(session: Session, *, user_id: uuid.UUID) -> ConfigVersion | None:
    """Versão vigente = a mais recente do usuário."""
    stmt = (
        select(ConfigVersion)
        .where(ConfigVersion.user_id == user_id)
        .order_by(ConfigVersion.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()
