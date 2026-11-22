"""Usuário (ADR-13): sem login na fase 1, mas o modelo já é multiusuário."""

import uuid

from sqlalchemy import Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base, CreatedAtMixin

# Usuário fixo da fase 1, criado pela migration inicial.
FIXED_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class User(CreatedAtMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
