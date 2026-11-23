"""Parâmetros de volatilidade guardados na configuração versionada (PRD §5.3 e §5.5, BRD §7.11).

Bloco `vol` de `config_versions.params`. Padrões aprovados: janelas 20 e 60 pregões, cobertura
mínima de 80% (BRD 1.3), close-to-close de média zero (PRD 1.5), janela de sincronização de 10 s
(QA-05), IV de referência pela mediana da última hora com mínimo de 3 negócios (QA-04) e prazo
constante de 21 dias úteis (QA-03, sugestão do BRD).
"""

from datetime import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vollab.db.models import ConfigVersion


class IntradayParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bar_minutes: int = Field(default=5, ge=1, le=60, description="Tamanho da barra (RN-VOL-08).")
    session_open: time = Field(default=time(10, 0), description="Início da grade (relógio de Brasília).")
    min_coverage: float = Field(
        default=0.8, gt=0, le=1, description="Fração mínima de barras com negócio para o pregão contar."
    )

    @field_validator("bar_minutes")
    @classmethod
    def _divides_hour(cls, v: int) -> int:
        if 60 % v:
            raise ValueError("bar_minutes deve dividir 60.")
        return v


class ImpliedParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_window_s: float = Field(default=10.0, gt=0, le=600, description="Defasagem máxima (RN-VOL-03).")
    reference_window_min: int = Field(
        default=60, ge=5, le=480, description="Janela final da sessão para a IV de referência (RN-VOL-06)."
    )
    reference_min_trades: int = Field(default=3, ge=1, le=100, description="Mínimo para usar a mediana.")
    dividend_protected_strikes: bool = Field(
        default=True,
        description=(
            "A B3 reduz o strike pelo provento na data ex (RN-DAD-03): na precificação, o strike "
            "efetivo no vencimento é K − proventos com data ex até o vencimento."
        ),
    )


class VolParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    close_to_close_mode: Literal["zero_mean", "demeaned"] = Field(
        default="zero_mean", description="Close-to-close oficial (PRD §5.5): média zero ou subtraída."
    )
    windows_bd: list[int] = Field(default=[20, 60], min_length=1, max_length=4)
    intraday: IntradayParams = Field(default_factory=IntradayParams)
    implied: ImpliedParams = Field(default_factory=ImpliedParams)
    constant_maturity_bd: int = Field(default=21, ge=5, le=252, description="Prazo da IV constante (QA-03).")
    ci_level: float = Field(default=0.90, gt=0.5, lt=1, description="Nível dos intervalos (QA-07).")

    @field_validator("windows_bd")
    @classmethod
    def _windows(cls, v: list[int]) -> list[int]:
        if any(w < 5 or w > 252 for w in v):
            raise ValueError("Janelas entre 5 e 252 pregões.")
        return sorted(set(v))


def vol_params_from_config(version: ConfigVersion) -> VolParams:
    raw: dict[str, Any] = dict(version.params.get("vol", {}))
    return VolParams.model_validate(raw)


class ForecastParams(BaseModel):
    """Bloco `forecast` de `config_versions.params` (PRD 1.7 §5.7; QA-07 e QA-08 resolvidas)."""

    model_config = ConfigDict(extra="forbid")

    ewma_lambda: float = Field(default=0.94, ge=0.90, le=0.99, description="λ da EWMA (eq. 4.1).")
    ewma_min_returns: int = Field(default=60, ge=20, le=1260, description="Amostra mínima da EWMA (QA-08).")
    combination_window_bd: int = Field(
        default=20, ge=5, le=252, description="Janela dos estimadores combinados (PRD §5.7)."
    )
    garch_min_returns: int = Field(default=240, ge=100, le=1260, description="Amostra mínima do GARCH.")
    garch_max_returns: int = Field(default=1260, ge=240, le=5040, description="Retornos usados no ajuste.")
    evaluation_horizons_bd: list[int] = Field(default=[21], min_length=1, max_length=4)
    min_evaluation_windows: int = Field(
        default=8, ge=3, le=100, description="Janelas não sobrepostas mínimas (QA-08, RN-PRV-02)."
    )
    bootstrap_reps: int = Field(default=2000, ge=200, le=20000)
    selected_model: Literal["ewma", "combination", "garch"] = Field(
        default="ewma", description="Modelo que alimenta o edge (RF-PRV-04), escolhido pelo usuário."
    )

    @field_validator("evaluation_horizons_bd")
    @classmethod
    def _horizons(cls, v: list[int]) -> list[int]:
        if any(h < 1 or h > 252 for h in v):
            raise ValueError("Horizontes entre 1 e 252 pregões.")
        return sorted(set(v))


def forecast_params_from_config(version: ConfigVersion) -> ForecastParams:
    raw: dict[str, Any] = dict(version.params.get("forecast", {}))
    return ForecastParams.model_validate(raw)
