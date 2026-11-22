"""Tabelas de referência (PRD §6.1): ativos, séries, ajustes, feriados, Selic e proventos."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base, CreatedAtMixin

MONEY = Numeric(18, 6)
RATE = Numeric(12, 8)


class Underlying(CreatedAtMixin, Base):
    """Ativo-objeto cadastrado pelo usuário (BRD §5.1: até 10 ativos)."""

    __tablename__ = "underlyings"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_underlyings_user_ticker"),
        CheckConstraint("ticker ~ '^[A-Z0-9]{4,12}$'", name="ticker_format"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    # Identifica as séries de opção (RN-DAD-02). Preenchido pelo COTAHIST se vier nulo.
    isin: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class OptionSeries(Base):
    """Série de opção. Identidade = (código, vencimento), pois a B3 reutiliza códigos (RN-DAD-02)."""

    __tablename__ = "option_series"
    __table_args__ = (
        UniqueConstraint("code", "expiry", name="uq_option_series_code_expiry"),
        CheckConstraint("option_type IN ('call', 'put')", name="option_type"),
        CheckConstraint("style IN ('european', 'american')", name="style"),
        CheckConstraint("style_source IN ('name_suffix', 'official_registry')", name="style_source"),
        Index("ix_option_series_isin_expiry", "underlying_isin", "expiry"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    underlying_isin: Mapped[str] = mapped_column(Text, nullable=False)
    option_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Strike vigente (o histórico diário fica em option_daily_stats; ajustes em series_adjustments).
    strike: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    style: Mapped[str] = mapped_column(Text, nullable=False)
    style_source: Mapped[str] = mapped_column(Text, nullable=False)
    is_weekly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="b3_cotahist")
    first_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_trade_date: Mapped[date] = mapped_column(Date, nullable=False)


class SeriesAdjustment(CreatedAtMixin, Base):
    """Ajuste de strike por provento, detectado no COTAHIST (RN-DAD-03)."""

    __tablename__ = "series_adjustments"
    __table_args__ = (UniqueConstraint("series_id", "effective_date", name="uq_series_adjustments_day"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    series_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("option_series.id"), nullable=False)
    # Primeiro pregão com o strike novo e último pregão observado com o anterior.
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    previous_date: Mapped[date] = mapped_column(Date, nullable=False)
    old_strike: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    new_strike: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Mudança de código: a série nova, quando a B3 trocar o código (não observado até 2026).
    new_series_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("option_series.id"))


class ExchangeHoliday(Base):
    """Dia sem pregão na B3 (RN-PRC-05, QA-02)."""

    __tablename__ = "exchange_holidays"
    __table_args__ = (
        CheckConstraint("source IN ('b3_official', 'national_list', 'b3_rule')", name="source"),
    )

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # Falso = ano ainda não publicado pela B3 (provisório).
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class RiskFreeRate(Base):
    """Selic diária (RN-PRC-03): decimal anual, base 252, capitalização exponencial (PRD §5.1)."""

    __tablename__ = "risk_free_rates"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    series_code: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raw_files.id"))


class CorporateAction(CreatedAtMixin, Base):
    """Dividendos e JCP (RN-PRC-02, RS-02). Yahoo = histórico estimado; ajuste de strike = oficial."""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("ticker", "ex_date", "source", name="uq_corporate_actions_ticker_day_source"),
        CheckConstraint("kind IN ('dividend', 'jcp', 'unknown')", name="kind"),
        CheckConstraint("source IN ('manual', 'yahoo', 'b3_strike_adjustment')", name="source"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raw_files.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
