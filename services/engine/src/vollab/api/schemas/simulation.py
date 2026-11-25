"""Simulador, dimensionamento e registro da entrada (PRD 1.9 §5.8 e §7; BRD 1.6 RF-SIM-01..05,
RN-SIZ-01..06, RF-DIA-01, RN-EDG-06).

Unidades do PRD §5.1: vol, prêmio, spreads e choques em decimal; dinheiro em BRL como texto decimal
(`_brl`); Greeks com a unidade no nome. `/simulations` e `/sizing` não gravam nada; só
`POST /positions` grava, e ele recalcula tudo no servidor a partir dos insumos.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from vollab.api.schemas.alerts import ManagementOut
from vollab.api.schemas.common import EstimatedValue
from vollab.api.schemas.journal import (
    AttributionOut,
    CleanText,
    Cs04Out,
    DeltaBandOut,
    EntryOut,
    HoldingOut,
    MarkOut,
    TotalsOut,
)
from vollab.api.schemas.portfolio import LimitsResponse

StructureName = Literal["short_straddle", "short_strangle", "covered_call", "long_straddle", "long_strangle"]
PriceBRL = Annotated[Decimal, Field(gt=0, le=Decimal("1000000"), max_digits=18, decimal_places=6)]
CostBRL = Annotated[Decimal, Field(ge=0, le=Decimal("10000000"), max_digits=18, decimal_places=6)]


# --- Entrada ---------------------------------------------------------------------------------


class LegInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: int = Field(ge=1)
    manual_price_brl: PriceBRL | None = Field(default=None, description="Preço do momento (RF-SIM-03).")
    manual_price_at: AwareDatetime | None = Field(default=None, description="Data e hora do preço manual.")

    @model_validator(mode="after")
    def _manual_has_time(self) -> "LegInput":
        if self.manual_price_brl is not None and self.manual_price_at is None:
            raise ValueError("Preço manual exige data e hora (manual_price_at).")
        return self


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(pattern=r"^[A-Za-z0-9]{4,12}$")
    structure: StructureName
    legs: list[LegInput] = Field(min_length=1, max_length=2)
    manual_spot_brl: PriceBRL | None = Field(default=None, description="Preço manual do ativo-objeto.")
    manual_spot_at: AwareDatetime | None = None
    lots: int = Field(default=1, ge=1, le=100_000, description="Lotes para os Greeks da posição.")

    @model_validator(mode="after")
    def _check(self) -> "SimulationRequest":
        if self.manual_spot_brl is not None and self.manual_spot_at is None:
            raise ValueError("Preço manual do ativo exige data e hora (manual_spot_at).")
        ids = [leg.series_id for leg in self.legs]
        if len(set(ids)) != len(ids):
            raise ValueError("Séries repetidas nas pernas.")
        return self


class SizingRequest(SimulationRequest):
    capital_brl: Decimal | None = Field(
        default=None,
        gt=0,
        le=Decimal("1e12"),
        max_digits=18,
        decimal_places=2,
        description="Capital alocado para opções (RN-SIZ-01); sem ele vale o da configuração.",
    )
    margin_per_lot_brl: PriceBRL | None = Field(default=None, description="Margem manual (RN-SIZ-06).")
    margin_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _margin_has_time(self) -> "SizingRequest":
        if self.margin_per_lot_brl is not None and self.margin_at is None:
            raise ValueError("Margem manual exige data e hora (margin_at).")
        return self


class ExecutedLeg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: int = Field(ge=1)
    price_brl: PriceBRL
    fees_brl: CostBRL = Decimal(0)
    brokerage_brl: CostBRL = Decimal(0)


class ExecutedStock(BaseModel):
    """Ação executada na entrada: a da venda coberta ou o hedge inicial (com sinal)."""

    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=-10_000_000, le=10_000_000)
    price_brl: PriceBRL
    fees_brl: CostBRL = Decimal(0)
    brokerage_brl: CostBRL = Decimal(0)


class RollLeg(BaseModel):
    """Fechamento de uma perna da posição de origem na rolagem (RN-GES-04)."""

    model_config = ConfigDict(extra="forbid")

    instrument: str = Field(pattern=r"^[A-Z0-9]{4,12}$")
    quantity: int = Field(ge=-10_000_000, le=10_000_000, description="Com sinal: reduz a perna até zero.")
    price_brl: Annotated[Decimal, Field(ge=0, le=Decimal("1000000"), max_digits=18, decimal_places=6)]
    fees_brl: CostBRL = Decimal(0)
    brokerage_brl: CostBRL = Decimal(0)


class RollFrom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_id: int = Field(ge=1)
    legs: list[RollLeg] = Field(min_length=1, max_length=4)


class PositionCreate(SizingRequest):
    """Registro da entrada (RF-DIA-01). `lots` = lotes executados. O engine recalcula edge, semáforo,
    simulação e dimensionamento; o cliente não impõe números calculados (PRD §7)."""

    base_config_version_id: int = Field(ge=1, description="409 se não for mais a vigente.")
    executed_legs: list[ExecutedLeg] = Field(min_length=1, max_length=2)
    stock: ExecutedStock | None = None
    executed_at: AwareDatetime
    note: CleanText | None = Field(default=None, max_length=2000)
    override_reason: CleanText | None = Field(
        default=None,
        min_length=10,
        max_length=2000,
        description='Obrigatório fora de "edge líquido" na direção da estrutura, acima do tamanho '
        "sugerido ou com limite da carteira ultrapassado (pró-forma).",
    )
    roll_from: RollFrom | None = Field(
        default=None, description="Rolagem: fecha as pernas da posição de origem na mesma transação."
    )


# --- Saída: cadeia ---------------------------------------------------------------------------


class ChainSeries(BaseModel):
    series_id: int
    code: str
    option_type: Literal["call", "put"]
    expiry: date
    strike: float
    effective_strike: float
    k_over_f: float
    iv: float | None = Field(description="IV de referência do pregão (RN-VOL-06); nula sem IV.")
    price_brl: str | None = Field(description="Preço BS com a IV de referência e o fechamento.")
    liquid: bool
    trades_count: int | None


class ChainResponse(BaseModel):
    ticker: str
    as_of: date | None
    spot_brl: str | None
    expiries: list[date]
    expiries_with_iv: list[date] = Field(description="Vencimentos com IV de referência no pregão.")
    expiry: date | None
    days_to_expiry_bd: int | None
    forward: float | None
    series: list[ChainSeries]
    suggestions: dict[str, list[int]] = Field(description="Séries sugeridas por estrutura (editáveis).")


# --- Saída: simulação ------------------------------------------------------------------------


class LegOut(BaseModel):
    series_id: int
    code: str
    option_type: Literal["call", "put"]
    quantity_per_lot: int = Field(description="Opções por lote, com sinal (− vendida).")
    strike: float
    effective_strike: float
    k_over_f: float
    band: Literal["low", "atm", "high"]
    price_brl: str
    price_origin: Literal["observed", "estimated", "manual"]
    price_at: datetime | None
    iv: EstimatedValue
    delta: float
    gamma: float
    vega_per_point: float
    theta_per_bd: float
    spread_conservative: float | None = Field(description="Spread relativo da faixa (estimativa).")


class StockOut(BaseModel):
    quantity_per_lot: int
    price_brl: str


class GreeksOut(BaseModel):
    delta_shares: float
    gamma: float
    vega_per_point_brl: float
    theta_per_bd_brl: float


class CostsOut(BaseModel):
    """Custos por lote em BRL e em pontos de vol (decimal). Sempre estimativa."""

    options_spread_brl: str
    options_fees_brl: str
    options_brokerage_brl: str
    stock_brl: str
    underlying_spread: float
    underlying_spread_estimated: bool
    options_vol_pts: float
    hedge_sell_vol_pts: float
    hedge_buy_vol_pts: float | None
    hedge_half_spread: float
    hedge_interval_bd: int
    total_sell_vol_pts: float
    total_buy_vol_pts: float | None
    band_hedge_cost_brl: str | None = Field(
        description="Custo médio do hedge pela regra de banda (simulação)."
    )


class PayoffCurve(BaseModel):
    label: str
    step_bd: int
    day: date
    pnl_brl: list[float] = Field(description="P&L por lote, sem hedge nem custos.")


class PayoffOut(BaseModel):
    spots: list[float]
    curves: list[PayoffCurve]


class PercentileOut(BaseModel):
    percentile: int
    pnl_brl: str


class DistributionOut(BaseModel):
    status: Literal["ok", "insufficient_data", "unavailable"]
    reason: str | None
    origin: Literal["estimated", "approximate"]
    paths: int
    seed: int
    sample_size: int
    sample_start: date | None
    sample_end: date | None
    delta_band: float
    delta_band_calibrated: bool
    iv_constant: bool = Field(description="IV de cada perna constante na simulação.")
    mean_brl: str | None
    std_brl: str | None
    variance_brl2: float | None
    percentiles: list[PercentileOut]
    es_level: float
    es_brl: str | None
    prob_loss: float | None
    mean_rehedges: float | None
    mean_band_hedge_cost_brl: str | None
    kamal_derman_std_brl: str | None = Field(description="Eq. 7.7 com hedge diário (aproximado).")
    hist_edges_brl: list[float]
    hist_counts: list[int]


class SimulationResponse(BaseModel):
    ticker: str
    structure: StructureName
    direction: Literal["sell", "buy"]
    dynamic_hedge: bool
    as_of: date
    expected_as_of: date
    expiry: date
    horizon_bd: int
    lots: int
    lot_size: int
    spot_brl: str
    spot_origin: Literal["observed", "manual"]
    spot_at: datetime | None
    rate: float = Field(description="Selic do pregão (decimal anual exponencial).")
    legs: list[LegOut]
    stock: StockOut | None
    iv: EstimatedValue = Field(description="IV da estrutura (ponderada pela vega), ex-evento.")
    iv_with_events: EstimatedValue
    events_removed: list[int]
    forecast: EstimatedValue
    normal_spread: EstimatedValue
    premium: EstimatedValue
    relative_edge: EstimatedValue
    threshold: EstimatedValue
    state: Literal["edge", "inconclusive", "no_edge", "unavailable"]
    signal_direction: Literal["sell", "buy"] | None
    direction_match: bool
    reason: str | None
    required_sell: float | None
    required_buy: float | None
    net_premium: float | None
    net_relative_edge: float | None
    expected_pnl_approx_brl: str | None = Field(description="Vega × (|p| − c) por lote (aproximado).")
    costs: CostsOut | None
    greeks_lot: GreeksOut
    greeks_position: GreeksOut
    payoff: PayoffOut
    distribution: DistributionOut
    expected_pnl_brl: str | None = Field(description="Média da distribuição por lote (RF-SIM-05).")
    model: str
    ci_level: float
    config_version_id: int
    engine_version: str


# --- Saída: dimensionamento ------------------------------------------------------------------


class StressOut(BaseModel):
    name: str
    spot_shock: float
    vol_shock: float
    loss_brl: str


class SizingOut(BaseModel):
    status: Literal["ok", "unavailable"]
    reason: str | None
    capital_brl: str | None
    kelly_fraction: float
    max_loss_fraction: float
    mu_brl: str | None = Field(description="P&L esperado por lote no limite inferior do edge.")
    variance_brl2: float | None
    es_brl: str | None
    stress: list[StressOut]
    max_loss_brl: str | None
    kelly_full_lots: float | None
    n_kelly: int
    n_cap: int | None
    n_final: int
    rule: Literal["kelly", "cap", "tie", "zero"]
    margin_per_lot_brl: str | None
    margin_total_brl: str | None
    margin_share_of_capital: float | None
    margin_origin: Literal["manual"] = "manual"
    stress_notes: list[str] = Field(description="Cenários de crise indisponíveis (o teto fica sem eles).")


class SizingResponse(BaseModel):
    simulation: SimulationResponse
    sizing: SizingOut
    limits: LimitsResponse = Field(description="Limites da carteira com a nova posição (pró-forma, PR-04).")


# --- Operações -------------------------------------------------------------------------------


class PositionSummary(BaseModel):
    id: int
    created_at: datetime
    ticker: str
    structure: StructureName
    direction: Literal["sell", "buy"]
    expiry: date
    lots: int
    edge_state: Literal["edge", "inconclusive", "no_edge"]
    model: str
    config_version_id: int
    overridden: bool
    status: Literal["open", "closed"] = Field(description="Derivado dos lançamentos (PRD 1.10 §5.9).")
    rolled_from_position_id: int | None
    pnl_total_brl: str | None = Field(description="Mercado + execução e custos, até a última marcação.")
    last_mark_date: date | None
    cs04_ratio: float | None
    error_days: int
    pending_expiry: list[str] = Field(description="Pernas vencidas ainda em aberto (LC-08).")
    ledger_error: str | None = Field(description="Livro de lançamentos inconsistente (RS-06), com o motivo.")


class ManualInputOut(BaseModel):
    kind: Literal["spot", "option_price", "margin"]
    instrument: str
    value_brl: str
    observed_at: datetime


class PositionOut(PositionSummary):
    as_of: date
    engine_version: str
    override_reason: str | None
    note: str | None
    entries: list[EntryOut]
    manual_inputs: list[ManualInputOut]
    decision_snapshot: dict[str, Any]
    holdings: list[HoldingOut]
    marks: list[MarkOut]
    attribution: list[AttributionOut]
    totals: TotalsOut | None
    cs04: Cs04Out
    delta_band: DeltaBandOut
    management: ManagementOut | None = Field(
        default=None, description="Regras de gestão da última avaliação (PRD 1.11 §5.10); nulo antes dela."
    )
