from typing import Any

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
