"""Marcação D-1, atribuição e cenários de crise (PRD 1.10 §5.9 e §6.5; BRD 1.7 RF-DIA-04, QA-12).

`daily_marks` e `pnl_attribution` são **derivadas**: o job `marks_recompute` as refaz a partir dos
lançamentos e dos dados de mercado (não são decisões; podem ser recalculadas). `crisis_measurements` é
por usuário: o episódio e a janela vêm da configuração de cada um.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base
from vollab.db.models.reference import MONEY


class DailyMark(Base):
    __tablename__ = "daily_marks"

    position_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("positions.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    spot: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    stock_qty: Mapped[int] = mapped_column(BigInteger, nullable=False)
    options_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    stock_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    delta_shares: Mapped[float] = mapped_column(Double, nullable=False)
    gamma: Mapped[float] = mapped_column(Double, nullable=False)
    vega_per_point_brl: Mapped[float] = mapped_column(Double, nullable=False)
    theta_per_bd_brl: Mapped[float] = mapped_column(Double, nullable=False)
    # Alguma perna em aberto repetiu a marcação anterior (rótulo "desatualizado").
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Por perna: quantidade, preço, IV, origem e Greeks (PRD §5.1).
    legs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PnlAttribution(Base):
    __tablename__ = "pnl_attribution"

    position_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("positions.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    delta_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    gamma_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    theta_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    vega_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    market_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    residual_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    execution_brl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Possível erro de lançamento (RS-06): resíduo acima da fração e do mínimo em R$.
    error_flag: Mapped[bool] = mapped_column(Boolean, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)


class CrisisMeasurement(Base):
    __tablename__ = "crisis_measurements"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'unavailable')", name="status"),
        CheckConstraint("vol_method IS NULL OR vol_method IN ('atm_iv', 'rv20')", name="vol_method"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    episode: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)
    price_shock: Mapped[float | None] = mapped_column(Double)  # retorno simples (−0,25 = queda de 25%)
    worst_day: Mapped[date | None] = mapped_column(Date)
    worst_day_return: Mapped[float | None] = mapped_column(Double)
    vol_shock: Mapped[float | None] = mapped_column(Double)  # pontos de vol em decimal
    vol_method: Mapped[str | None] = mapped_column(Text)
    vol_before: Mapped[float | None] = mapped_column(Double)
    vol_after: Mapped[float | None] = mapped_column(Double)
    # Proventos do episódio conferidos na fonte (Yahoo); sem eles, os retornos não são ajustados.
    dividends_checked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
