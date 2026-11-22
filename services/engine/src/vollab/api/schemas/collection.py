"""Contrato da coleta (PRD §7: /collection) e dos ativos (/underlyings)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

RunStatus = Literal["queued", "running", "succeeded", "partial", "interrupted", "failed"]
ItemStatus = Literal["pending", "ok", "empty", "failed"]
ItemGroup = Literal[
    "cotahist_annual", "cotahist_daily", "selic", "dividends", "underlying_trades", "option_trades"
]
GapKind = Literal[
    "missing_bar",
    "r4_diverged",
    "calendar_alert",
    "cotahist_failed",
    "underlying_trades_failed",
    "options_failed",
]


class RunSummary(BaseModel):
    id: int
    status: RunStatus
    origin: Literal["manual", "initial_load"] = Field(
        description="`initial_load` = primeira coleta (carga inicial)."
    )
    reference_date: date = Field(
        description="Data em que a coleta foi disparada; coleta-se até o pregão anterior."
    )
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    message: str | None
    config_version_id: int


class GroupCount(BaseModel):
    group: ItemGroup
    count: int


class CollectionPendingResponse(BaseModel):
    reference_date: date = Field(description="Último pregão a coletar (D-1).")
    intraday_start: date = Field(description="Primeiro pregão da janela de negócios intradiários.")
    bars_start: date = Field(description="Primeiro pregão da janela de OHLC oficial.")
    is_initial_load: bool
    pending_days: list[date] = Field(description="Pregões com algum item pendente, em ordem crescente.")
    counts: list[GroupCount]
    known_requests: int = Field(description="Requisições já conhecidas (sem as opções a determinar).")
    days_awaiting_cotahist: int = Field(
        description="Pregões sem COTAHIST baixado: as séries de opção deles são definidas depois dele."
    )
    estimated_seconds: int = Field(
        description="Tempo estimado das requisições conhecidas, no ritmo configurado."
    )
    requests_per_second: float
    data_source: Literal["live", "fixtures"] = Field(
        description="`fixtures` = fonte simulada (E2E ou demonstração)."
    )
    active_run: RunSummary | None
    last_run: RunSummary | None


class ProgressCounts(BaseModel):
    total: int
    pending: int
    ok: int
    empty: int
    failed: int


class GroupProgressOut(ProgressCounts):
    group: ItemGroup


class ItemOut(BaseModel):
    source: str
    group: ItemGroup
    key: str = Field(description="Ticker, ano (COTAHIST anual) ou `-`.")
    trade_date: date
    underlying: str | None
    status: ItemStatus
    permanent: bool = Field(description="Falha definitiva (HTTP 404 de ticker): não será tentada de novo.")
    error: str | None


class CollectionRunResponse(BaseModel):
    run: RunSummary
    totals: ProgressCounts
    groups: list[GroupProgressOut]
    current: ItemOut | None = Field(description="Próximo item a processar (coleta em andamento).")
    estimated_seconds_remaining: int
    recent_failures: list[ItemOut]


class GapOut(BaseModel):
    underlying: str | None
    trade_date: date
    kind: GapKind
    detail: str
    count: int


class GapSummary(BaseModel):
    kind: GapKind
    count: int


class CollectionGapsResponse(BaseModel):
    reference_date: date
    bars_start: date
    intraday_start: date
    summary: list[GapSummary]
    gaps: list[GapOut] = Field(description="Lacunas por ativo e data, mais recentes primeiro (até `limit`).")
    gaps_total: int
    failures: list[ItemOut] = Field(description="Último estado de cada item com falha (até `limit`).")
    failures_total: int


class UnderlyingOut(BaseModel):
    ticker: str
    isin: str | None = Field(description="ISIN do ativo; identifica as séries de opção (RN-DAD-02).")
    active: bool


class UnderlyingCreate(BaseModel):
    ticker: str = Field(pattern=r"^[A-Z0-9]{4,12}$", description="Código de negociação, ex.: PETR4.")


class UnderlyingUpdate(BaseModel):
    active: bool
