"""Previsão de RV e avaliação de modelos (PRD 1.7 §5.7 e §6.4; RF-PRV-01..04, RN-PRV-01/02).

Calculadas no worker (job `forecast_recompute`) depois do recálculo de volatilidade; as telas só
leem. Vols em decimal anualizado em base 252 (`double precision`).
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base

FORECAST_MODELS = ("ewma", "combination", "garch")
EVALUATED = (*FORECAST_MODELS, "rv_c2c_20", "implied")
STATUSES = ("ok", "insufficient_data", "unavailable")


class RvForecast(Base):
    """Previsão por ativo, pregão de origem, modelo e horizonte, com intervalo e o estado do modelo."""

    __tablename__ = "rv_forecasts"
    __table_args__ = (
        CheckConstraint(f"model IN {FORECAST_MODELS}", name="model"),
        CheckConstraint(f"status IN {STATUSES}", name="status"),
        CheckConstraint("(status = 'ok') = (vol IS NOT NULL)", name="value_status"),
        CheckConstraint("ci_origin IS NULL OR ci_origin IN ('estimated', 'approximate')", name="ci_origin"),
    )

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    horizon_bd: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    vol: Mapped[float | None] = mapped_column(Double)
    ci_low: Mapped[float | None] = mapped_column(Double)
    ci_high: Mapped[float | None] = mapped_column(Double)
    # estimated = quantis do erro avaliado; approximate = fallback χ² (QA-07).
    ci_origin: Mapped[str | None] = mapped_column(Text)
    ci_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # Estado do modelo em t: EWMA {lambda, next_var}; GARCH {omega, alpha, beta, next_var, loglik};
    # combinação {next_var, components}; sempre n_returns. Permite outros horizontes na leitura.
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)


class ForecastEvaluation(Base):
    """Erro de previsão por modelo ou baseline, só janelas não sobrepostas (RF-PRV-03, RN-PRV-01)."""

    __tablename__ = "forecast_evaluations"
    __table_args__ = (
        CheckConstraint(f"model IN {EVALUATED}", name="model"),
        CheckConstraint("status IN ('ok', 'insufficient_data')", name="status"),
    )

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    horizon_bd: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    n_windows: Mapped[int] = mapped_column(Integer, nullable=False)
    # Origens descartadas por motivo: {"no_forecast": k, "incomplete_realized": k}.
    discarded: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    bias: Mapped[float | None] = mapped_column(Double)
    mae: Mapped[float | None] = mapped_column(Double)
    rmse: Mapped[float | None] = mapped_column(Double)
    rmse_ci_low: Mapped[float | None] = mapped_column(Double)
    rmse_ci_high: Mapped[float | None] = mapped_column(Double)
    # Razão de RMSE contra cada baseline: {baseline: {value, ci_low, ci_high, n, status}}.
    ratios: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Quantis de ln(RV/σ̂) para o intervalo empírico da previsão (QA-07).
    log_q_low: Mapped[float | None] = mapped_column(Double)
    log_q_high: Mapped[float | None] = mapped_column(Double)
    first_origin: Mapped[date | None] = mapped_column(Date)
    last_origin: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    ci_level: Mapped[float] = mapped_column(Double, nullable=False)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ForecastEvaluationPoint(Base):
    """Uma origem avaliada: previsão × RV realizada na janela (origem, fim] (T-REF-09, CS-03)."""

    __tablename__ = "forecast_evaluation_points"
    __table_args__ = (CheckConstraint(f"model IN {EVALUATED}", name="model"),)

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    horizon_bd: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    origin: Mapped[date] = mapped_column(Date, primary_key=True)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    forecast: Mapped[float | None] = mapped_column(Double)
    realized: Mapped[float | None] = mapped_column(Double)
    # Por que a origem não entrou: no_forecast | incomplete_realized (NULL = avaliada).
    discard_reason: Mapped[str | None] = mapped_column(Text)
