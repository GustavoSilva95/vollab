"""Parâmetros da coleta guardados na configuração versionada (PRD §5.3, BRD §7.11, QA-06).

A configuração vigente é a última versão do usuário. Se ainda não houver nenhuma, a primeira
coleta cria a versão inicial com os padrões aprovados (QA-06, BRD 1.2). Os demais blocos
de parâmetros (custos, edge, Kelly etc.) entram nas suas etapas, na mesma estrutura.
"""

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from vollab.db.config_store import create_config_version, current_config_version
from vollab.db.models import ConfigVersion


class LiquidityFilter(BaseModel):
    """Série elegível para a coleta intradiária e para a IV (QA-06, RN-VOL-04)."""

    model_config = ConfigDict(extra="forbid")

    min_trades: int = Field(default=20, ge=1, description="Mínimo de negócios no dia (COTAHIST).")
    moneyness_min: Decimal = Field(default=Decimal("0.9"), gt=0, description="K/S mínimo.")
    moneyness_max: Decimal = Field(default=Decimal("1.1"), gt=0, description="K/S máximo.")
    monthly_expiries: int = Field(default=2, ge=1, le=6, description="Próximos vencimentos mensais.")
    include_weeklies: bool = Field(default=False, description="Incluir séries semanais (W1..W5).")

    @model_validator(mode="after")
    def _range(self) -> "LiquidityFilter":
        if self.moneyness_min >= self.moneyness_max:
            raise ValueError("moneyness_min deve ser menor que moneyness_max.")
        return self


class CollectionWindow(BaseModel):
    """Janelas da carga (RF-DAD-05)."""

    model_config = ConfigDict(extra="forbid")

    intraday_bd: int = Field(default=63, ge=1, le=504, description="Pregões de negócios intradiários.")
    daily_bars_bd: int = Field(default=252, ge=21, le=1260, description="Pregões de OHLC oficial.")


class CollectionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    liquidity: LiquidityFilter = Field(default_factory=LiquidityFilter)
    window: CollectionWindow = Field(default_factory=CollectionWindow)


def params_from_config(version: ConfigVersion) -> CollectionParams:
    raw: dict[str, Any] = dict(version.params.get("collection", {}))
    return CollectionParams.model_validate(raw)


def ensure_config_version(session: Session, *, user_id: uuid.UUID) -> ConfigVersion:
    """Versão vigente; cria a inicial com os padrões se o usuário ainda não tiver nenhuma."""
    version = current_config_version(session, user_id=user_id)
    if version is not None and "collection" in version.params:
        return version
    params: dict[str, Any] = dict(version.params) if version is not None else {}
    params["collection"] = CollectionParams().model_dump(mode="json")
    return create_config_version(
        session,
        user_id=user_id,
        params=params,
        note="Parâmetros padrão da coleta (QA-06: ≥ 20 negócios, K/S 0,9–1,1, 2 mensais).",
    )
