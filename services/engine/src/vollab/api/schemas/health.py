from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(description="`degraded` quando o banco não responde.")
    engine_version: str = Field(description="Versão do engine (git sha do build).")
    database: Literal["ok", "unavailable"]
    last_collection_at: datetime | None = Field(
        default=None,
        description="Fim da última coleta concluída (com ou sem falhas). Nulo antes da primeira.",
    )
    data_source: Literal["live", "fixtures"] = Field(
        description="`fixtures` = fonte simulada por arquivos salvos (E2E ou demonstração)."
    )
