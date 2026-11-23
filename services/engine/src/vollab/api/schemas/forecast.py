"""Previsão de RV e avaliação de modelos (PRD 1.7 §5.7 e §7; RF-PRV-01..04, CS-03)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vollab.api.schemas.common import EstimatedValue

ModelName = Literal["ewma", "combination", "garch"]
EvaluatedName = Literal["ewma", "combination", "garch", "rv_c2c_20", "implied"]


class ModelState(BaseModel):
    """Estado do modelo na origem (o que gera a previsão em qualquer horizonte)."""

    n_returns: int | None = Field(default=None, description="Retornos diários válidos usados.")
    ewma_lambda: float | None = Field(default=None, description="λ da EWMA (eq. 4.1).")
    omega: float | None = Field(default=None, description="ω do GARCH (variância diária, decimal).")
    alpha: float | None = None
    beta: float | None = None
    persistence: float | None = Field(default=None, description="α + β.")
    long_run_vol: float | None = Field(default=None, description="√(252·V), V = ω/(1 − α − β).")
    components: list[str] | None = Field(default=None, description="Estimadores na combinação.")
    window_bd: int | None = Field(default=None, description="Janela dos estimadores combinados.")


class ForecastOut(BaseModel):
    model: EvaluatedName
    kind: Literal["model", "baseline"]
    forecast: EstimatedValue = Field(description="RV prevista para o horizonte (vol anualizada, decimal).")
    selected: bool = Field(description="É o modelo em uso no edge (RF-PRV-04).")
    eligible: bool = Field(description="Tem avaliação disponível no horizonte (RF-PRV-02, RN-PRV-02).")
    eligibility_reason: str | None = None
    state: ModelState | None = None


class ForecastsResponse(BaseModel):
    ticker: str
    as_of: date | None = Field(description="Pregão de origem da previsão.")
    horizon_bd: int
    evaluated_horizons_bd: list[int]
    selected_model: ModelName
    ci_level: float
    items: list[ForecastOut]


class RatioOut(BaseModel):
    baseline: Literal["rv_c2c_20", "implied"]
    n_windows: int = Field(description="Origens em que modelo e baseline existem (pareadas).")
    ratio: EstimatedValue = Field(description="RMSE do modelo ÷ RMSE do baseline (< 1 = melhor).")


class EvaluationRow(BaseModel):
    model: EvaluatedName
    kind: Literal["model", "baseline"]
    status: Literal["ok", "insufficient_data"]
    n_windows: int = Field(description="Janelas não sobrepostas avaliadas.")
    discarded_no_forecast: int
    discarded_incomplete_realized: int
    first_origin: date | None
    last_origin: date | None
    bias: float | None = Field(description="Média de previsão − realizada (decimal; > 0 = superestima).")
    mae: float | None
    rmse: EstimatedValue
    ratios: list[RatioOut]


class EvaluationResponse(BaseModel):
    ticker: str
    horizon_bd: int
    evaluated_horizons_bd: list[int]
    min_windows: int = Field(description="Amostra mínima para sair de 'dados insuficientes' (QA-08).")
    ci_level: float
    selected_model: ModelName
    computed_at: datetime | None
    config_version_id: int | None
    engine_version: str | None
    rows: list[EvaluationRow]


class EvaluationPointOut(BaseModel):
    origin: date
    window_end: date
    forecast: float | None
    forecast_ci_low: float | None = Field(
        description="Intervalo da previsão (QA-07), para a banda do gráfico."
    )
    forecast_ci_high: float | None
    realized: float | None
    discard_reason: Literal["no_forecast", "incomplete_realized"] | None


class EvaluationSeries(BaseModel):
    model: EvaluatedName
    ci_origin: Literal["estimated", "approximate"] = Field(
        description="estimated = quantis do erro avaliado; approximate = só o erro de amostragem (χ²)."
    )
    points: list[EvaluationPointOut]


class EvaluationPointsResponse(BaseModel):
    ticker: str
    horizon_bd: int
    series: list[EvaluationSeries]


class ModelSelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ModelName


class ModelSelectionOut(BaseModel):
    selected_model: ModelName
    config_version_id: int
    created: bool = Field(description="Uma versão nova de configuração foi criada.")
