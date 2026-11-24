"""Carteira, stress, limites e cenários de crise (PRD 1.10 §5.9 e §7; BRD 1.7 RF-RSK-01..04, QA-12).

Calculados na leitura a partir da última marcação D-1 de cada operação aberta; nada é gravado.
Choques e frações em decimal (PRD §5.1); dinheiro em texto decimal.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExposureOut(BaseModel):
    ticker: str | None = None
    expiry: date | None = None
    delta_shares: float
    delta_brl: float
    gamma: float = Field(description="Variação do delta (ações) por R$ 1 no ativo.")
    gamma_1pct_brl: float = Field(description="P&L de um movimento de 1% no ativo: ½·Γ·(0,01·S)².")
    vega_per_point_brl: float
    theta_per_bd_brl: float
    market_value_brl: float


class PortfolioResponse(BaseModel):
    positions_open: int
    mark_dates: dict[str, date] = Field(description="Última marcação usada por ativo.")
    warnings: list[str]
    total: ExposureOut | None
    by_ticker: list[ExposureOut]
    by_expiry: list[ExposureOut]


class PnlByTicker(BaseModel):
    ticker: str
    pnl_brl: str


class PnlByExpiry(BaseModel):
    ticker: str
    expiry: date
    pnl_brl: str


class ShockOut(BaseModel):
    ticker: str
    spot_shock: float = Field(description="Relativo (−0,10 = queda de 10%).")
    vol_shock: float = Field(description="Pontos de vol em decimal.")


class ScenarioOut(BaseModel):
    name: str
    label: str
    kind: Literal["standard", "crisis", "custom"]
    pnl_brl: str
    loss_brl: str
    by_ticker: list[PnlByTicker]
    by_expiry: list[PnlByExpiry]
    missing_tickers: list[str] = Field(description="Ativos sem choque neste cenário (crise indisponível).")
    origin: Literal["estimated", "approximate", "manual"]
    shocks: list[ShockOut] = Field(description="Choque aplicado a cada ativo.")


class StressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spot_shock: float = Field(ge=-0.9, le=0.9, description="Relativo (−0,10 = queda de 10%).")
    vol_shock: float = Field(ge=-0.5, le=2.0, description="Pontos de vol em decimal (0,10 = +10 pontos).")


class LimitOut(BaseModel):
    name: Literal["stress_loss", "vega_total", "underlying_concentration", "expiry_concentration"]
    scope: str | None
    value: float | None
    limit: float
    usage: float | None = Field(description="value ÷ limite (1,0 = no limite).")
    state: Literal["ok", "breached", "unavailable"]
    reason: str | None = None
    calibrated: bool = False


class LimitsResponse(BaseModel):
    capital_brl: str | None
    scenarios: list[ScenarioOut]
    limits: list[LimitOut]
    breached: bool
    warnings: list[str]


class CrisisEpisodeOut(BaseModel):
    key: str
    label: str
    start: date
    end: date


class CrisisOut(BaseModel):
    ticker: str
    episode: str
    label: str
    status: Literal["ok", "unavailable"]
    origin: Literal["approximate", "manual"]
    price_shock: float | None
    vol_shock: float | None
    reason: str | None
    window_start: date | None = None
    window_end: date | None = None
    worst_day: date | None = None
    worst_day_return: float | None = None
    vol_method: Literal["atm_iv", "rv20"] | None = None
    vol_before: float | None = None
    vol_after: float | None = None
    dividends_checked: bool | None = None
    measured_at: datetime | None = None


class CrisisResponse(BaseModel):
    episodes: list[CrisisEpisodeOut]
    horizon_bd: int
    values: list[CrisisOut]
    job: Literal["queued", "running"] | None = Field(description="Medição em andamento, se houver.")


class CrisisMeasureOut(BaseModel):
    queued: bool = Field(description="False: já havia uma medição igual ou mais ampla na fila.")
    job_id: int | None
