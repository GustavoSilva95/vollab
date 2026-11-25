"""Configuração versionada (PRD §5.3, BRD §7.11).

Cada versão é um snapshot imutável de todos os parâmetros. Editar = criar uma versão nova.
A imutabilidade é garantida no banco por trigger (migration 0001), não só no código.
"""

import uuid
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base, CreatedAtMixin


class ConfigVersion(CreatedAtMixin, Base):
    __tablename__ = "config_versions"
    # FK composta de `alerts` (Etapa 8, revisão de segurança I-1).
    __table_args__ = (UniqueConstraint("id", "user_id", name="id_user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
