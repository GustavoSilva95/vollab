"""Configuração versionada (PRD §5.3 e 1.8 §7; BRD §7.11). Versões nunca são alteradas: editar cria
uma versão nova. O Pydantic valida o snapshot inteiro (PRD §7: autoridade de validação)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from vollab.analytics.params import (
    CostParams,
    EdgeParams,
    ForecastParams,
    JournalParams,
    ManagementParams,
    RiskParams,
    SimulationParams,
    SizingParams,
    VolParams,
)
from vollab.collection.params import CollectionParams


class ConfigParams(BaseModel):
    """Todos os blocos de parâmetros, com os padrões preenchidos."""

    model_config = ConfigDict(extra="forbid")

    collection: CollectionParams = Field(default_factory=CollectionParams)
    vol: VolParams = Field(default_factory=VolParams)
    forecast: ForecastParams = Field(default_factory=ForecastParams)
    costs: CostParams = Field(default_factory=CostParams)
    edge: EdgeParams = Field(default_factory=EdgeParams)
    simulation: SimulationParams = Field(default_factory=SimulationParams)
    sizing: SizingParams = Field(default_factory=SizingParams)
    journal: JournalParams = Field(default_factory=JournalParams)
    risk: RiskParams = Field(default_factory=RiskParams)
    management: ManagementParams = Field(default_factory=ManagementParams)


class ConfigVersionOut(BaseModel):
    id: int
    created_at: datetime
    note: str | None
    params: ConfigParams


class ConfigVersionSummary(BaseModel):
    id: int
    created_at: datetime
    note: str | None
    current: bool


class ConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: ConfigParams
    note: str = Field(min_length=1, max_length=500, description="O que mudou e por quê.")
    base_version_id: int = Field(
        ge=1,
        description="Versão sobre a qual a edição foi feita; 409 se não for mais a vigente (evita desfazer "
        "em silêncio uma mudança feita em outra tela, como a troca do modelo do edge).",
    )


class ConfigCreateOut(BaseModel):
    id: int
    created: bool = Field(description="False: os parâmetros eram iguais aos vigentes; nada foi gravado.")
