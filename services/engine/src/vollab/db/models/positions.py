"""Operações e retrato da decisão (PRD 1.9 §5.4, §5.8 e §6.5; BRD RF-DIA-01, RN-EDG-06, CS-01).

As três tabelas são **imutáveis** (trigger da migration 0007, como `config_versions`): uma entrada
registrada nunca é alterada nem apagada. O estado da posição (aberta / encerrada) vem dos lançamentos
(Etapa 7), não de uma coluna atualizável. Dinheiro em `NUMERIC(18,6)`, nunca float (PRD §5.1).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base, CreatedAtMixin
from vollab.db.models.reference import MONEY

STRUCTURES = ("short_straddle", "short_strangle", "covered_call", "long_straddle", "long_strangle")
DIRECTIONS = ("sell", "buy")
EDGE_STATES = ("edge", "inconclusive", "no_edge")
ENTRY_KINDS = ("entry", "hedge", "strike_adjustment", "exercise", "assignment", "exit", "roll", "void")
MANUAL_KINDS = ("spot", "option_price", "margin")


class Position(CreatedAtMixin, Base):
    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint(f"structure IN {STRUCTURES}", name="structure"),
        CheckConstraint(f"direction IN {DIRECTIONS}", name="direction"),
        CheckConstraint(f"edge_state IN {EDGE_STATES}", name="edge_state"),
        CheckConstraint("lots > 0", name="lots"),
        Index("ix_positions_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    structure: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    lots: Mapped[int] = mapped_column(Integer, nullable=False)
    # Semáforo no momento da entrada (RN-EDG-06). "Indisponível" nunca entra (CS-01 por construção).
    edge_state: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    override_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    decision_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Etapa 7 (RN-GES-04): a rolagem liga a posição nova à de origem.
    rolled_from_position_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("positions.id"))


class PositionEntry(CreatedAtMixin, Base):
    """Lançamento tipado (RF-DIA-02/03, PRD 1.10 §5.9). Imutável: erro se corrige por estorno (`void`)."""

    __tablename__ = "position_entries"
    __table_args__ = (
        CheckConstraint(f"kind IN {ENTRY_KINDS}", name="kind"),
        CheckConstraint("quantity <> 0", name="quantity"),
        CheckConstraint("price >= 0 AND fees_brl >= 0 AND brokerage_brl >= 0", name="non_negative"),
        CheckConstraint(
            "kind <> 'void' OR (linked_entry_id IS NOT NULL AND void_reason IS NOT NULL)", name="void_linked"
        ),
        CheckConstraint("kind <> 'strike_adjustment' OR strike_after > 0", name="strike_after"),
        Index("ix_position_entries_position", "position_id"),
        Index(
            "ux_position_entries_void_once",
            "linked_entry_id",
            unique=True,
            postgresql_where=text("kind = 'void'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    position_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("positions.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Código da série ou ticker do ativo-objeto (hedge, ação da venda coberta).
    instrument: Mapped[str] = mapped_column(Text, nullable=False)
    series_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("option_series.id"))
    # Quantidade em opções ou ações, com sinal (+ compra, − venda).
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fees_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    brokerage_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    linked_entry_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("position_entries.id"))
    # Etapa 7: novo strike efetivo (ajuste de strike), motivo do estorno, nota e versões.
    strike_after: Mapped[Decimal | None] = mapped_column(MONEY)
    void_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    config_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("config_versions.id"))
    engine_version: Mapped[str | None] = mapped_column(Text)


class ManualInput(CreatedAtMixin, Base):
    """Preços do momento e margem informados pelo usuário, com hora (RF-SIM-03, RN-SIZ-06)."""

    __tablename__ = "manual_inputs"
    __table_args__ = (
        CheckConstraint(f"kind IN {MANUAL_KINDS}", name="kind"),
        CheckConstraint("value > 0", name="positive"),
        Index("ix_manual_inputs_position", "position_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    position_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("positions.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    instrument: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
