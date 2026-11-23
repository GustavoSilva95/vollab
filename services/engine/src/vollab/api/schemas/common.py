from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProblemDetails(BaseModel):
    """Erro no formato RFC 9457 (PRD §7)."""

    type: str = Field(default="about:blank", description="URI que identifica o tipo do problema.")
    title: str = Field(description="Resumo curto do problema, em português.")
    status: int = Field(description="Código HTTP.")
    detail: str | None = Field(default=None, description="Explicação específica desta ocorrência.")
    instance: str | None = Field(default=None, description="Caminho da requisição que falhou.")
    errors: list[dict[str, Any]] | None = Field(
        default=None, description="Erros de validação por campo (apenas em 422)."
    )


class EstimatedValue(BaseModel):
    """Valor com proveniência (PRD §5.2). `insufficient_data` → a interface nunca mostra número."""

    value: float | None = Field(description="Valor (vol: decimal anualizado em base 252).")
    ci_low: float | None = Field(default=None, description="Limite inferior do intervalo.")
    ci_high: float | None = Field(default=None, description="Limite superior do intervalo.")
    ci_level: float = Field(description="Nível do intervalo (QA-07), ex.: 0.90.")
    status: Literal["ok", "insufficient_data", "unavailable"]
    origin: Literal["observed", "estimated", "manual", "approximate"]
    as_of: date = Field(description="Pregão de referência.")
    stale: bool = Field(description="Dado mais antigo que o último pregão.")
    reason: str | None = Field(default=None, description="Motivo de status ≠ ok ou de ausência de intervalo.")
    calibrated: bool | None = Field(default=None, description="Para limiares e spread normal (Etapa 5).")
