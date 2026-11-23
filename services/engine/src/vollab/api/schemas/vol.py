"""Contrato de séries, volatilidade e eventos (PRD §7: Ativos e séries, Volatilidade, Eventos).

Unidades (PRD §5.1): vols em decimal anualizado em base 252; prazos com sufixo `_bd` (dias úteis);
preços em BRL. Salto de evento (`jump`) = desvio-padrão do retorno no dia do evento, decimal **não
anualizado** (referência técnica, eq. 5.3).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from vollab.api.schemas.common import EstimatedValue

EstimatorName = Literal[
    "close_to_close",
    "close_to_close_demeaned",
    "parkinson",
    "garman_klass",
    "rogers_satchell",
    "yang_zhang",
    "intraday_5m",
]
EventKind = Literal["earnings", "ex_dividend", "ex_jcp", "copom", "macro", "expiry"]
EditableEventKind = Literal["earnings", "ex_dividend", "ex_jcp", "copom", "macro"]


# --- Resumo e séries ------------------------------------------------------------------------


class IntradayQuality(BaseModel):
    trade_date: date
    bars_total: int
    bars_with_trades: int
    coverage: float = Field(description="Fração de barras de 5 min com negócio (decimal).")
    complete: bool = Field(description="Cobertura ≥ mínimo configurado (RN-VOL-08).")


class IvQuality(BaseModel):
    """Relatório de qualidade da sincronização (RN-VOL-03) no pregão."""

    trade_date: date
    trades_valid: int
    trades_synced: int
    trades_lag_discarded: int = Field(description="Pares acima da janela máxima de sincronização.")
    trades_no_solution: int = Field(description="Negócios sincronizados sem IV (preço fora dos limites).")
    sync_window_s: float


class UnderlyingSummary(BaseModel):
    ticker: str
    isin: str | None
    as_of: date | None = Field(description="Último pregão com OHLC oficial.")
    close: Decimal | None
    expected_as_of: date = Field(description="Último pregão esperado (D-1).")
    intraday: IntradayQuality | None
    iv_quality: IvQuality | None
    computed_at: datetime | None = Field(description="Último recálculo de volatilidade no worker.")


class PricePoint(BaseModel):
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    dividend: Decimal | None = Field(
        description="Provento com data ex no pregão (ajusta o retorno, RN-VOL-07)."
    )


class PriceHistory(BaseModel):
    ticker: str
    points: list[PricePoint] = Field(description="Só pregões com OHLC; a interface mostra as lacunas.")
    calendar: list[date] = Field(
        description="Todos os pregões do período (para quebrar a linha nas lacunas)."
    )


class SeriesOut(BaseModel):
    code: str
    expiry: date
    option_type: Literal["call", "put"]
    style: Literal["european", "american"]
    is_weekly: bool
    strike: Decimal = Field(description="Strike do COTAHIST no pregão.")
    effective_strike: Decimal | None = Field(description="Strike no vencimento, com a proteção de proventos.")
    days_to_expiry_bd: int
    trades_count: int = Field(description="Negócios no pregão (COTAHIST).")
    liquid: bool = Field(description="Passa no filtro de liquidez (RN-VOL-04).")
    iv: EstimatedValue | None = Field(description="IV de referência do pregão (RN-VOL-06).")
    iv_status: Literal["ok", "low_sample", "no_iv"] | None
    trades_used: int | None


class SeriesResponse(BaseModel):
    ticker: str
    as_of: date | None
    series: list[SeriesOut]


# --- RV ---------------------------------------------------------------------------------------


class RealizedPoint(BaseModel):
    as_of: date
    vol: float | None = Field(description="Vol exibida (com correção de viés no close-to-close).")
    variance_annual: float | None = Field(description="Variância anualizada sem correção (previsão/GARCH).")
    status: Literal["ok", "insufficient_data"]
    reason: str | None
    missing_days: int


class EstimatorSeries(BaseModel):
    estimator: EstimatorName
    window_bd: int
    latest: EstimatedValue
    points: list[RealizedPoint]


class RealizedVolResponse(BaseModel):
    ticker: str
    windows_bd: list[int]
    official_close_to_close: Literal["close_to_close", "close_to_close_demeaned"] = Field(
        description="Forma do close-to-close usada como oficial (config `close_to_close_mode`)."
    )
    estimators: list[EstimatorSeries]


# --- IV ---------------------------------------------------------------------------------------


class SmilePointOut(BaseModel):
    code: str
    option_type: Literal["call", "put"]
    strike: Decimal
    effective_strike: Decimal
    moneyness: float = Field(description="K efetivo / forward (decimal).")
    iv: float
    status: Literal["ok", "low_sample"]
    trades_used: int
    out_of_the_money: bool


class SmileResponse(BaseModel):
    ticker: str
    as_of: date | None
    expiries: list[date] = Field(description="Vencimentos com IV de séries líquidas no pregão.")
    expiry: date | None
    days_to_expiry_bd: int | None
    forward: float | None
    atm_iv: EstimatedValue | None
    points: list[SmilePointOut] = Field(description="Só séries líquidas (RN-VOL-04).")


class TermPointOut(BaseModel):
    expiry: date
    days_to_expiry_bd: int
    is_weekly: bool
    atm_iv: EstimatedValue


class TermStructureResponse(BaseModel):
    ticker: str
    as_of: date | None
    points: list[TermPointOut]


class ConstantMaturityOut(BaseModel):
    as_of: date
    iv: EstimatedValue = Field(description="IV ATM de prazo constante (interpolação em variância total).")
    iv_ex_event: EstimatedValue = Field(description="Sem a variância dos saltos de evento (RN-EVT-03).")
    events_removed: list[int] = Field(description="Ids dos eventos cujo salto foi removido.")
    fallback_expiry: date | None = Field(
        description="Sem dois vencimentos: o vencimento cuja ATM é exibida (RN-VOL-05)."
    )
    fallback_bd: int | None = Field(description="Prazo efetivo da ATM exibida no lugar.")
    fallback_iv: float | None
    lower_expiry: date | None
    upper_expiry: date | None


class ConstantMaturityResponse(BaseModel):
    ticker: str
    target_bd: int
    latest: ConstantMaturityOut | None
    history: list[ConstantMaturityOut]


# --- Eventos ----------------------------------------------------------------------------------


class EventOut(BaseModel):
    id: int | None = Field(description="Nulo para vencimentos (derivados das séries, não editáveis).")
    ticker: str | None
    kind: EventKind
    event_date: date
    status: Literal["confirmed", "estimated"]
    amount: Decimal | None = Field(description="Valor por ação (ex-dividendo/ex-JCP), BRL.")
    note: str | None
    derived: bool = Field(description="Vencimento derivado do COTAHIST (não editável).")


class EventCreate(BaseModel):
    ticker: str | None = Field(default=None, pattern=r"^[A-Z0-9]{4,12}$")
    kind: EditableEventKind
    event_date: date
    status: Literal["confirmed", "estimated"]
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=6)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _rules(self) -> "EventCreate":
        _check_event(self.kind, self.ticker, self.amount)
        return self


class EventUpdate(BaseModel):
    event_date: date | None = None
    status: Literal["confirmed", "estimated"] | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=6)
    note: str | None = Field(default=None, max_length=500)


def _check_event(kind: str, ticker: str | None, amount: Decimal | None) -> None:
    if kind in ("ex_dividend", "ex_jcp") and amount is None:
        raise ValueError("Ex-dividendo e ex-JCP exigem o valor por ação.")
    if kind not in ("ex_dividend", "ex_jcp") and amount is not None:
        raise ValueError("Valor por ação só para ex-dividendo e ex-JCP.")
    if kind not in ("copom", "macro") and ticker is None:
        raise ValueError("Este tipo de evento exige o ativo.")


class EventJumpOut(BaseModel):
    event: EventOut
    as_of: date
    jump: EstimatedValue = Field(description="σ do retorno no dia do evento (decimal, não anualizado).")
    expected_move: float | None = Field(description="Movimento esperado E|R| = sqrt(2/π)·σ (eq. 5.4).")
    term_structure_value: float | None
    term_structure_reason: str | None
    expiry1: date | None
    expiry2: date | None
    historical_value: float | None
    historical_ci_low: float | None
    historical_ci_high: float | None
    historical_n: int = Field(description="Datas de resultado passadas com retorno disponível.")


class EventJumpsResponse(BaseModel):
    ticker: str
    as_of: date | None
    jumps: list[EventJumpOut]
