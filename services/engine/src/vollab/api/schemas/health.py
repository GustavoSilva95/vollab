from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(description="`degraded` quando o banco não responde.")
    engine_version: str = Field(description="Versão do engine (git sha do build).")
    database: Literal["ok", "unavailable"]
    last_collection_at: datetime | None = Field(
        default=None,
        description="Fim da última coleta concluída. Sempre nulo até a Etapa 2 (coleta).",
    )
