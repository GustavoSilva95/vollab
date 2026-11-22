"""Tabelas de mercado (PRD §6.2): arquivos brutos, negócios, OHLC e estatísticas de opções."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base
from vollab.db.models.reference import MONEY

VOLUME = Numeric(24, 2)

RAW_SOURCES = ("b3_trades", "b3_cotahist_daily", "b3_cotahist_annual", "bcb_selic", "yahoo_dividends")


class RawFile(Base):
    """Cada download preservado em `data/raw/` (ADR-06, RF-DAD-04).

    O arquivo em disco é endereçado pelo SHA-256 do conteúdo (nome gerado pelo engine,
    PRD-NF-05) e nunca é sobrescrito. Uma linha por consulta: o mesmo conteúdo (ex.: o ZIP
    vazio de um feriado) pode servir a várias consultas.
    """

    __tablename__ = "raw_files"
    __table_args__ = (
        CheckConstraint(f"source IN {RAW_SOURCES}", name="source"),
        CheckConstraint("parse_status IN ('pending', 'ok', 'empty', 'error')", name="parse_status"),
        Index("ix_raw_files_query", "source", "query_key", "query_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # Ticker consultado (negócios, Yahoo) ou outro identificador da consulta (ano do anual etc.).
    query_key: Mapped[str] = mapped_column(Text, nullable=False)
    query_date: Mapped[date | None] = mapped_column(Date)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    http_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    content_format: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    parse_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    parse_error: Mapped[str | None] = mapped_column(Text)


# Negócios brutos normalizados (RF-DAD-01). Particionada por mês do pregão de referência
# (PRD-QA-02). A tabela é criada por DDL na migration 0003; este objeto serve às consultas.
# Chave: (pregão, instrumento, DataNegocio, ID, ação) — IDs reiniciam a cada pregão e a
# linha de cancelamento repete o ID do negócio cancelado.
trades = Table(
    "trades",
    Base.metadata,
    Column("reference_date", Date, nullable=False),
    Column("instrument", Text, nullable=False),
    Column("trade_date", Date, nullable=False),
    Column("trade_id", BigInteger, nullable=False),
    Column("update_action", SmallInteger, nullable=False),
    Column("price", MONEY, nullable=False),
    Column("quantity", BigInteger, nullable=False),
    Column("traded_at", DateTime(timezone=True), nullable=False),
    Column("session_type", SmallInteger, nullable=False),
    Column("buyer", Integer),
    Column("seller", Integer),
    # Resultado da R4 (RN-DAD-01) calculado na ingestão, sobre o arquivo inteiro.
    Column("r4_valid", Boolean, nullable=False),
    Column("raw_file_id", BigInteger, nullable=False),
    PrimaryKeyConstraint(
        "reference_date", "instrument", "trade_date", "trade_id", "update_action", name="pk_trades"
    ),
    postgresql_partition_by="RANGE (reference_date)",
)


class DailyBar(Base):
    """OHLC oficial do ativo-objeto por pregão (COTAHIST, RN-DAD-01) e a verificação pela R4."""

    __tablename__ = "daily_bars"
    __table_args__ = (
        CheckConstraint(
            "r4_check IN ('not_checked', 'ok', 'diverged')",
            name="r4_check",
        ),
    )

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    isin: Mapped[str] = mapped_column(Text, nullable=False)
    open: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    high: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    low: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    close: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    trades_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    volume: Mapped[Decimal] = mapped_column(VOLUME, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    raw_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("raw_files.id"), nullable=False)
    r4_check: Mapped[str] = mapped_column(Text, nullable=False, server_default="not_checked")
    # Campos que divergiram do oficial (ex.: "trades_count,close"); nulo se ok ou não verificado.
    r4_diff: Mapped[str | None] = mapped_column(Text)


class OptionDailyStat(Base):
    """Linha do COTAHIST por série e pregão (RF-DAD-02, QA-06): base do pré-filtro da coleta."""

    __tablename__ = "option_daily_stats"
    __table_args__ = (Index("ix_option_daily_stats_date", "trade_date"),)

    series_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("option_series.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    strike: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    open: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    high: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    low: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    last: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    best_bid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    best_ask: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    trades_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    volume: Mapped[Decimal] = mapped_column(VOLUME, nullable=False)
    raw_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("raw_files.id"), nullable=False)
