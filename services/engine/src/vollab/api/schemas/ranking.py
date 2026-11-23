"""Ranking, custos e spreads (PRD 1.8 §5.6.1 e §7; RF-RNK-01/02, RN-EDG-01..07, RN-CST-01..03).

Unidades do PRD §5.1: vol, prêmio e custos em pontos de vol em decimal (0,01 = 1 ponto); edge
relativo, spread normal e spreads relativos adimensionais; dinheiro em string decimal (BRL).
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from vollab.api.schemas.common import EstimatedValue

EdgeStateOut = Literal["edge", "inconclusive", "no_edge", "unavailable"]
DirectionOut = Literal["sell", "buy"]
ModelOut = Literal["ewma", "combination", "garch"]


class CostBreakdown(BaseModel):
    """Custos da estrutura de referência (straddle ATM teórico, ida e volta) e do hedge."""

    option_spread_central: float = Field(description="Spread relativo das opções ATM (mediana).")
    option_spread_conservative: float = Field(description="Spread relativo usado no semáforo (RN-EDG-04).")
    option_spread_quoted: float | None = Field(
        description="Conferência: spread de fechamento do COTAHIST (fora do custo, PRD 1.8.1)."
    )
    underlying_spread: float = Field(description="Spread relativo do ativo-objeto (conservador).")
    underlying_spread_estimated: bool = Field(description="False: piso do tick, sem negócios para medir.")
    spread_days: int = Field(description="Pregões com estimativa na janela.")
    spread_series: int = Field(description="Séries ATM somadas na janela.")
    reference_contracts: int
    straddle_premium_brl: str = Field(description="Prêmio de um straddle (call + put), por opção.")
    straddle_vega_brl: str = Field(description="Vega do straddle por 1 ponto de vol (0,01).")
    spread_brl: str
    fees_brl: str
    brokerage_brl: str
    options_vol_pts: float = Field(description="Custo das opções em pontos de vol.")
    hedge_sell_vol_pts: float = Field(description="Custo do hedge vendido em vol (Leland).")
    hedge_buy_vol_pts: float | None = Field(description="Comprado em vol; None: o hedge consome tudo.")
    hedge_half_spread: float = Field(description="λ de Leland: meio spread do ativo + taxa.")
    hedge_interval_bd: int
    total_sell_vol_pts: float
    total_buy_vol_pts: float | None


class RankingEvent(BaseModel):
    id: int
    kind: str
    event_date: date
    status: str
    ticker: str | None


class LiquidityOut(BaseModel):
    liquid_series: int = Field(description="Séries que passam o filtro de liquidez (QA-06) no pregão.")
    option_trades: int
    option_volume_brl: str


class TermSlope(BaseModel):
    value: EstimatedValue = Field(description="ATM do 2º vencimento − ATM do 1º, pontos de vol.")
    expiry1: date | None = None
    expiry2: date | None = None
    days1_bd: int | None = None
    days2_bd: int | None = None


class RankingRow(BaseModel):
    position: int = Field(description="Posição no ranking (1 = melhor).")
    ticker: str
    as_of: date | None = Field(description="Pregão da IV usada.")
    state: EdgeStateOut
    direction: DirectionOut | None = Field(description="Venda ou compra de vol (sinal do prêmio).")
    reason: str | None = Field(description="Motivo de 'indisponível' ou da aproximação.")
    approximate: bool = Field(description="Fallback de IV (ATM do vencimento disponível), RN-VOL-05.")
    horizon_bd: int = Field(description="Prazo efetivo usado (= prazo constante sem fallback).")
    model: ModelOut
    iv: EstimatedValue = Field(description="IV ex-evento (RN-EVT-03).")
    iv_with_events: EstimatedValue
    events_removed: list[int]
    forecast: EstimatedValue = Field(description="RV prevista pelo modelo escolhido, com intervalo.")
    normal_spread: EstimatedValue = Field(description="Spread normal s (calibrated = false → não calibrado).")
    normal_spread_pairs: int
    premium: EstimatedValue = Field(description="IV − σ̂(1 + s), pontos de vol (RN-EDG-01).")
    relative_edge: EstimatedValue = Field(description="Prêmio ÷ σ̂ (RN-EDG-02).")
    net_relative_edge: float | None = Field(description="(|prêmio| − custos) ÷ σ̂ na direção.")
    net_premium: float | None = Field(description="|prêmio| − custos na direção, pontos de vol.")
    expected_pnl_brl: str | None = Field(description="≈ vega × pontos líquidos, por straddle de referência.")
    threshold: EstimatedValue = Field(description="Limiar L (RN-EDG-05), pontos de vol.")
    required_sell: float | None = Field(description="Custos de venda + L.")
    required_buy: float | None = Field(description="Custos de compra + L (None: compra inviável).")
    costs: CostBreakdown | None
    iv_rank: EstimatedValue = Field(description="(IV − mín)/(máx − mín) no último ano.")
    iv_percentile: EstimatedValue
    iv_rank_days: int
    skew: EstimatedValue = Field(description="IV(K/F baixo) − IV(K/F alto), pontos de vol.")
    skew_expiry: date | None
    term_slope: TermSlope
    events: list[RankingEvent]
    liquidity: LiquidityOut | None


class RankingResponse(BaseModel):
    expected_as_of: date = Field(description="Último pregão esperado (para marcar dados antigos).")
    horizon_bd: int
    selected_model: ModelOut
    ci_level: float
    config_version_id: int
    engine_version: str
    rows: list[RankingRow]


class SpreadDayOut(BaseModel):
    trade_date: date
    band: Literal["low", "atm", "high", "underlying"]
    n_series: int
    n_trades: int
    rel_median: float | None
    rel_p75: float | None
    quoted_rel_median: float | None


class SpreadsResponse(BaseModel):
    ticker: str
    moneyness_bands: tuple[float, float]
    lookback_bd: int
    days: list[SpreadDayOut]
