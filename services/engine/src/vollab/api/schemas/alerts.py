"""Alertas e gestão da operação (PRD 1.11 §5.10 e §7; BRD 1.8 RN-GES-01..07, RS-07).

Vol em decimal, dinheiro em texto decimal (`_brl`), prazos em dias úteis (`_bd`) (PRD §5.1). O
detalhe de cada regra é um objeto com os números do disparo (chaves com a unidade no nome).
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vollab.api.schemas.journal import CleanText

AlertKind = Literal["hedge", "exit", "roll", "limit", "dividend"]
AlertRule = Literal[
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
]
AlertState = Literal["active", "seen", "resolved"]
RuleStateName = Literal["ok", "triggered", "disabled", "unavailable"]


class AlertOut(BaseModel):
    id: int
    kind: AlertKind
    rule: AlertRule
    position_id: int | None
    ticker: str | None = Field(description="Ativo da operação; nulo nos limites de carteira.")
    structure: str | None
    scope_key: str
    state: AlertState
    triggered_at: datetime
    triggered_as_of: date
    last_as_of: date
    details: dict[str, Any]
    config_version_id: int = Field(description="Configuração vigente no disparo.")
    evaluated_config_version_id: int = Field(description="Configuração da última avaliação.")
    engine_version: str
    resolved_at: datetime | None
    resolved_by: Literal["auto", "user"] | None
    resolution_note: str | None


class AlertPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["seen", "resolved"]
    note: CleanText | None = Field(default=None, max_length=500, description="Nota ao resolver (opcional).")


class AlertsResponse(BaseModel):
    alerts: list[AlertOut]
    counts: dict[AlertState, int] = Field(description="Alertas por estado (todos, não só os listados).")


class RuleOut(BaseModel):
    rule: AlertRule
    kind: AlertKind
    state: RuleStateName
    scope_key: str
    reason: str | None
    details: dict[str, Any]


class PositionEdgeOut(BaseModel):
    """Edge relativo líquido da posição aberta (RN-GES-02): na direção dela, com os custos de manter
    (hedge por Leland) e de fechar."""

    as_of: date
    horizon_bd: int
    iv: float
    iv_with_events: float
    sigma: float
    sigma_low: float
    sigma_high: float
    normal_spread: float
    normal_spread_calibrated: bool
    premium: float
    premium_low: float
    premium_high: float
    cost_hold_vol_pts: float | None
    cost_close_vol_pts: float
    cost_close_brl: str
    net_relative_edge: float | None
    net_relative_low: float | None
    net_relative_high: float | None
    origin: Literal["estimated", "approximate"]
    model: str
    reason: str | None


class RollLegOut(BaseModel):
    series_id: int
    code: str


class RollOut(BaseModel):
    """Rolagem avaliada (RN-GES-04): destino, semáforo com o custo de fechar a posição atual."""

    status: Literal["ok", "unavailable"]
    suggested: bool
    min_dte_bd: int
    reason: str | None = None
    as_of: date | None = None
    expiry: date | None = None
    horizon_bd: int | None = None
    structure: str | None = None
    legs: list[RollLegOut] = Field(default_factory=list)
    lots: int | None = None
    state: Literal["edge", "inconclusive", "no_edge", "unavailable"] | None = None
    signal_direction: Literal["sell", "buy"] | None = None
    iv: float | None = None
    sigma: float | None = None
    premium: float | None = None
    premium_low: float | None = None
    premium_high: float | None = None
    cost_sell_vol_pts: float | None = None
    cost_buy_vol_pts: float | None = None
    close_cost_brl: str | None = None
    close_cost_vol_pts: float | None = None
    net_relative_edge: float | None = None


class ManagementOut(BaseModel):
    as_of: date | None = Field(description="Pregão da marcação avaliada; nulo sem marcação D-1.")
    evaluated_at: datetime
    config_version_id: int
    rules: list[RuleOut]
    edge: PositionEdgeOut | None
    roll: RollOut | None
    alerts: list[AlertOut]
