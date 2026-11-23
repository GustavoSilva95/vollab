"""Tabelas derivadas de volatilidade (PRD §6.2, §5.5): calculadas no worker após a coleta.

As telas só leem estas tabelas; negócios brutos nunca são agregados numa requisição (PRD-NF-06).
Vols e variâncias são decimais anualizados em base 252 (`double precision`: não são dinheiro);
preços continuam em NUMERIC (PRD §5.1).
"""

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base
from vollab.db.models.reference import MONEY

ESTIMATORS = (
    "close_to_close",
    "close_to_close_demeaned",
    "parkinson",
    "garman_klass",
    "rogers_satchell",
    "yang_zhang",
    "intraday_5m",
)


class IntradaySession(Base):
    """Resumo do pregão intradiário do ativo-objeto (RN-VOL-08): grade, cobertura e variância."""

    __tablename__ = "intraday_sessions"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    session_open: Mapped[time] = mapped_column(Time, nullable=False)
    session_close: Mapped[time] = mapped_column(Time, nullable=False)
    bar_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    bars_total: Mapped[int] = mapped_column(Integer, nullable=False)
    bars_with_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage: Mapped[float] = mapped_column(Double, nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Σ ln(Pᵢ/Pᵢ₋₁)² da abertura oficial ao fechamento oficial, sem a noite (variância diária).
    intraday_variance: Mapped[float] = mapped_column(Double, nullable=False)
    trades_used: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IntradayBar(Base):
    """Barra de 5 min: último preço válido pela R4 (barra vazia repete o anterior)."""

    __tablename__ = "intraday_bars"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    bar_start: Mapped[time] = mapped_column(Time, primary_key=True)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    trades_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RealizedVol(Base):
    """RV por ativo, pregão de referência, estimador e janela (RF-VOL-01, PRD §5.5)."""

    __tablename__ = "realized_vols"
    __table_args__ = (
        CheckConstraint(f"estimator IN {ESTIMATORS}", name="estimator"),
        CheckConstraint("status IN ('ok', 'insufficient_data')", name="status"),
        CheckConstraint(
            "(status = 'ok') = (vol IS NOT NULL AND variance_annual IS NOT NULL)", name="value_status"
        ),
    )

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    estimator: Mapped[str] = mapped_column(Text, primary_key=True)
    window_bd: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    # Variância anualizada SEM correção de viés (alimenta previsão e GARCH).
    variance_annual: Mapped[float | None] = mapped_column(Double)
    # Vol exibida: corrigida por b₀(n) ou c₄(n) no close-to-close (PRD §5.5).
    vol: Mapped[float | None] = mapped_column(Double)
    missing_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # Código do motivo (a interface monta o texto): missing_days | incomplete_sessions | non_positive.
    reason: Mapped[str | None] = mapped_column(Text)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )


class ImpliedVol(Base):
    """IV por negócio de opção, sincronizada com o ativo-objeto (RF-VOL-02, RN-VOL-03)."""

    __tablename__ = "implied_vols"

    series_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("option_series.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    trade_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    option_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    underlying_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    lag_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # Strike efetivo usado (com a proteção de proventos da B3, se houver provento até o vencimento).
    strike: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    days_to_expiry_bd: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rate_continuous: Mapped[float] = mapped_column(Double, nullable=False)
    pv_dividends: Mapped[float] = mapped_column(Double, nullable=False)
    iv: Mapped[float | None] = mapped_column(Double)
    # vollab.quant.pricing.IvStatus (0 = ok).
    iv_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class OptionDailyQuote(Base):
    """IV de referência diária por série (RN-VOL-06) e o relatório de qualidade da sincronização."""

    __tablename__ = "option_daily_quotes"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'low_sample', 'no_iv')", name="status"),
        Index("ix_option_daily_quotes_date", "trade_date"),
    )

    series_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("option_series.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    iv: Mapped[float | None] = mapped_column(Double)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    trades_valid: Mapped[int] = mapped_column(Integer, nullable=False)
    trades_synced: Mapped[int] = mapped_column(Integer, nullable=False)
    trades_lag_discarded: Mapped[int] = mapped_column(Integer, nullable=False)
    trades_no_solution: Mapped[int] = mapped_column(Integer, nullable=False)
    trades_used: Mapped[int] = mapped_column(Integer, nullable=False)
    # Preço BS com a IV de referência e o fechamento oficial do ativo (RN-VOL-06).
    implied_price: Mapped[Decimal | None] = mapped_column(MONEY)
    underlying_close: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Strike do COTAHIST no pregão e o efetivo no vencimento (proteção de proventos, RN-DAD-03).
    strike: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    effective_strike: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    days_to_expiry_bd: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Passa no filtro de liquidez (RN-VOL-04): só as líquidas entram no smile e na ATM.
    liquid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )


class AtmTermPoint(Base):
    """IV ATM por vencimento (RF-VOL-05, estrutura a termo)."""

    __tablename__ = "atm_term_structure"
    __table_args__ = (CheckConstraint("status IN ('ok', 'unavailable')", name="status"),)

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    expiry: Mapped[date] = mapped_column(Date, primary_key=True)
    days_to_expiry_bd: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    forward: Mapped[float] = mapped_column(Double, nullable=False)
    atm_iv: Mapped[float | None] = mapped_column(Double)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    lower_strike: Mapped[float | None] = mapped_column(Double)
    upper_strike: Mapped[float | None] = mapped_column(Double)
    is_weekly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )


class ConstantMaturityVol(Base):
    """IV ATM de prazo constante, sem a remoção de eventos (RF-VOL-03, RN-VOL-05, QA-03).

    A versão ex-evento (RN-EVT-03) depende do calendário do usuário e é calculada na leitura.
    """

    __tablename__ = "constant_maturity_vols"
    __table_args__ = (CheckConstraint("status IN ('ok', 'unavailable')", name="status"),)

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    target_bd: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    iv: Mapped[float | None] = mapped_column(Double)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    lower_expiry: Mapped[date | None] = mapped_column(Date)
    upper_expiry: Mapped[date | None] = mapped_column(Date)
    # Sem dois vencimentos: a ATM do vencimento disponível, rotulada com o prazo efetivo (RN-VOL-05).
    fallback_expiry: Mapped[date | None] = mapped_column(Date)
    fallback_bd: Mapped[int | None] = mapped_column(SmallInteger)
    fallback_iv: Mapped[float | None] = mapped_column(Double)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
