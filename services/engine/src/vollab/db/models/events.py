"""Calendário de eventos do usuário (PRD §6.4, RF-EVT-01/02).

Cadastro manual, com marcação confirmada/estimada. Ex-dividendo e ex-JCP levam o valor por ação
e geram um provento `manual` em `corporate_actions` (RS-02: proventos futuros são manuais), que
entra no ajuste dos retornos (RN-VOL-07) e na precificação (RN-PRC-01/02).
Vencimentos de opções não são cadastrados: vêm das séries do COTAHIST (derivados na leitura).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base, CreatedAtMixin
from vollab.db.models.reference import MONEY

EVENT_KINDS = ("earnings", "ex_dividend", "ex_jcp", "copom", "macro")
EVENT_KINDS_WITH_AMOUNT = ("ex_dividend", "ex_jcp")
MARKET_WIDE_KINDS = ("copom", "macro")


class Event(CreatedAtMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(f"kind IN {EVENT_KINDS}", name="kind"),
        CheckConstraint("status IN ('confirmed', 'estimated')", name="status"),
        CheckConstraint(f"(kind IN {EVENT_KINDS_WITH_AMOUNT}) = (amount IS NOT NULL)", name="amount_by_kind"),
        CheckConstraint("amount IS NULL OR amount > 0", name="amount_positive"),
        CheckConstraint(f"kind IN {MARKET_WIDE_KINDS} OR ticker IS NOT NULL", name="ticker_by_kind"),
        Index("ix_events_user_date", "user_id", "event_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    # Nulo = evento de mercado (Copom, macro), sem ativo.
    ticker: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Pregão cujo retorno contém o evento (resultado após o fechamento → pregão seguinte).
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
