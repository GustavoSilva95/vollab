"""Diário, marcação D-1 e atribuição (PRD 1.10 §5.9 e §7; BRD 1.7 RF-DIA-02..04, RS-06, CS-04).

Dinheiro em texto decimal (`_brl`), vol em decimal, Greeks com a unidade no nome (PRD §5.1).
`POST /positions/{id}/entries` recebe só insumos; o engine valida pela reexecução do livro.
"""

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(value: str) -> str:
    """Texto livre do usuário: sem espaços nas pontas e sem caracteres de controle (o Postgres recusa
    NUL; os outros não têm uso aqui). Revisão de segurança da Etapa 7, M-3. Etapa 8 (M-6): também sem
    controles C1 nem caracteres de formatação (Unicode `Cc`/`Cf`, como as marcas bidirecionais, que
    invertem o texto na tela)."""
    if _CONTROL.search(value) or any(
        unicodedata.category(ch) in ("Cc", "Cf") and ch not in "\t\n" for ch in value
    ):
        raise ValueError("Texto com caractere de controle ou de formatação.")
    return value.strip()


# O mínimo de tamanho vale depois do corte dos espaços.
CleanText = Annotated[str, AfterValidator(clean_text)]

UserEntryKind = Literal["hedge", "strike_adjustment", "exercise", "assignment", "exit", "void"]
EntryKindName = Literal[
    "entry", "hedge", "strike_adjustment", "exercise", "assignment", "exit", "roll", "void"
]
MoneyIn = Annotated[Decimal, Field(ge=0, le=Decimal("10000000"), max_digits=18, decimal_places=6)]


class EntryCreate(BaseModel):
    """Lançamento (RF-DIA-02/03). Estorno (`void`): só `linked_entry_id`, `void_reason` e a data."""

    model_config = ConfigDict(extra="forbid")

    kind: UserEntryKind
    executed_at: AwareDatetime
    instrument: str | None = Field(default=None, pattern=r"^[A-Z0-9]{4,12}$")
    quantity: int | None = Field(
        default=None,
        ge=-10_000_000,
        le=10_000_000,
        description="Com sinal (+ compra, − venda). Exercício/designação: variação da perna de opção. "
        "Ajuste de strike: quantidade da perna depois do ajuste.",
    )
    price_brl: MoneyIn | None = Field(
        default=None, description="Preço executado; no exercício e na designação, o strike efetivo."
    )
    fees_brl: MoneyIn = Decimal(0)
    brokerage_brl: MoneyIn = Decimal(0)
    strike_after_brl: Annotated[Decimal, Field(gt=0, le=Decimal("1000000"), decimal_places=6)] | None = None
    linked_entry_id: int | None = Field(default=None, ge=1, description="Lançamento estornado (`void`).")
    void_reason: CleanText | None = Field(default=None, min_length=10, max_length=2000)
    note: CleanText | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check(self) -> "EntryCreate":
        if self.kind == "void":
            if self.linked_entry_id is None or not self.void_reason or len(self.void_reason) < 10:
                raise ValueError("Estorno exige linked_entry_id e void_reason (motivo, mín. 10 caracteres).")
            return self
        if self.instrument is None or self.quantity is None or self.price_brl is None:
            raise ValueError("Lançamento exige instrument, quantity e price_brl.")
        if self.quantity == 0:
            raise ValueError("Quantidade zero.")
        if self.kind == "strike_adjustment" and self.strike_after_brl is None:
            raise ValueError("Ajuste de strike exige strike_after_brl.")
        return self


class EntryOut(BaseModel):
    id: int
    kind: EntryKindName
    instrument: str
    series_id: int | None
    quantity: int
    price_brl: str
    fees_brl: str
    brokerage_brl: str
    executed_at: datetime
    linked_entry_id: int | None
    strike_after_brl: str | None
    void_reason: str | None
    note: str | None
    voided_by: int | None = Field(description="Estorno que anulou este lançamento.")


class HoldingOut(BaseModel):
    instrument: str
    series_id: int | None
    quantity: int


class MarkLegOut(BaseModel):
    code: str
    quantity: int
    price_brl: str
    iv: float | None
    origin: Literal["observed", "approximate", "stale", "expired"]
    delta: float
    gamma: float
    vega_per_point: float
    theta_per_bd: float


class MarkOut(BaseModel):
    trade_date: date
    spot_brl: str
    stock_qty: int
    options_value_brl: str
    stock_value_brl: str
    delta_shares: float
    gamma: float
    vega_per_point_brl: float
    theta_per_bd_brl: float
    stale: bool
    legs: list[MarkLegOut]


class AttributionOut(BaseModel):
    trade_date: date
    delta_brl: str
    gamma_brl: str
    theta_brl: str
    vega_brl: str
    residual_brl: str = Field(description="Sempre exibido (RF-DIA-04).")
    market_brl: str
    execution_brl: str = Field(description="Execução e custos, fora do resíduo.")
    total_brl: str
    stale: bool
    error_flag: bool = Field(description="Possível erro de lançamento (RS-06).")


class Cs04Out(BaseModel):
    ratio: float | None = Field(description="Σ|resíduo| ÷ Σ(|delta|+|gamma|+|theta|+|vega|) na vida.")
    target: float
    ok: bool | None
    error_days: int


class DeltaBandOut(BaseModel):
    as_of: date | None
    delta_shares: float | None
    half_width_shares: float
    calibrated: bool
    state: Literal["inside", "outside", "unavailable"]


class TotalsOut(BaseModel):
    delta_brl: str
    gamma_brl: str
    theta_brl: str
    vega_brl: str
    residual_brl: str
    market_brl: str
    execution_brl: str
    total_brl: str
