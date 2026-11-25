"""Alertas de gestão da operação (PRD 1.11 §5.10 e §6.5; BRD 1.8 RN-GES-01..07, RS-07).

- `alerts`: um alerta por disparo de uma regra. Ciclo de vida `active` → `seen` → `resolved`; nunca é
  apagado (o papel da aplicação não tem DELETE). Um trigger protege as colunas do disparo e torna o
  alerta resolvido imutável, exceto `persisting` (verdadeiro → falso): resolvido pelo usuário com a
  condição ainda valendo, ele segura a reabertura até a condição sumir.
- `position_management`: estado mais recente de cada regra por posição (derivado, refeito pelo job
  `alerts_evaluate`), lido por `GET /positions/{id}`; nenhum endpoint de leitura avalia regras.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base

ALERT_KINDS = ("hedge", "exit", "roll", "limit", "dividend")
ALERT_RULES = (
    "hedge_band",
    "hedge_time",
    "exit_edge",
    "exit_dte",
    "exit_profit",
    "exit_stop",
    "roll_suggested",
    "limit_stress",
    "limit_vega",
    "limit_underlying",
    "limit_expiry",
    "dividend_upcoming",
    "strike_adjustment_pending",
)
ALERT_STATES = ("active", "seen", "resolved")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(f"kind IN {ALERT_KINDS}", name="kind"),
        CheckConstraint(f"rule IN {ALERT_RULES}", name="rule"),
        CheckConstraint(f"state IN {ALERT_STATES}", name="state"),
        CheckConstraint("resolved_by IS NULL OR resolved_by IN ('auto', 'user')", name="resolved_by"),
        CheckConstraint(
            "(state = 'resolved') = (resolved_at IS NOT NULL AND resolved_by IS NOT NULL)", name="resolution"
        ),
        Index(
            "ux_alerts_open_key",
            "user_id",
            "rule",
            text("coalesce(position_id, 0)"),
            "scope_key",
            unique=True,
            postgresql_where=text("state <> 'resolved'"),
        ),
        Index("ix_alerts_user_state", "user_id", "state"),
        Index("ix_alerts_position", "position_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    # Nulo nos limites de carteira.
    position_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("positions.id"))
    # Limite e ativo/vencimento, data ex do provento ou série ajustada; "" quando a regra é única.
    scope_key: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    state: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    triggered_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    last_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    evaluated_config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    persisting: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class PositionManagement(Base):
    """Última avaliação das regras de uma posição (derivada; refeita pelo `alerts_evaluate`)."""

    __tablename__ = "position_management"

    position_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("positions.id"), primary_key=True)
    as_of: Mapped[date | None] = mapped_column(Date)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    edge: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    roll: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
