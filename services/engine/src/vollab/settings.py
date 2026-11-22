"""Configuração por variáveis de ambiente (ADR-14, PRD-NF-09).

Nenhum segredo tem valor padrão: a URL do banco vem do ambiente (`.env` fora do git).
Parâmetros de negócio editáveis pelo usuário (filtros de liquidez, janelas) ficam em
`config_versions` (PRD §5.3), não aqui.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    # B-5 (revisão de segurança da Etapa 1): a URL carrega a senha; SecretStr evita que ela
    # apareça em repr, logs ou tracebacks. Use `database_url.get_secret_value()`.
    database_url: SecretStr = Field(
        description="URL SQLAlchemy do Postgres, com o driver psycopg (postgresql+psycopg://...).",
    )
    # PRD-NF-01: só escuta na interface local. Dentro do container o compose
    # sobrescreve para 0.0.0.0 e publica a porta apenas em 127.0.0.1 do host.
    engine_host: str = "127.0.0.1"
    engine_port: int = 8000
    # Hosts aceitos no cabeçalho Host / X-Forwarded-Host (defesa contra DNS rebinding).
    allowed_hosts: list[str] = Field(default=["127.0.0.1", "localhost", "[::1]"])
    # Versão gravada no retrato da decisão (PRD §5.4): git sha do build.
    engine_version: str = "dev"
    log_level: str = "INFO"
    log_json: bool = False
    # Worker (ADR-08)
    worker_poll_interval_s: float = Field(default=1.0, gt=0)
    worker_stale_lock_s: float = Field(default=600.0, gt=0)

    # --- Coleta (Etapa 2) ---
    # Cache bruto imutável (ADR-06). Relativo ao diretório de trabalho do processo.
    raw_data_dir: Path = Path("data/raw")
    # `live` baixa das fontes reais; `fixtures` lê arquivos salvos (E2E e demonstração).
    # Nenhum teste de CI usa `live` (PRD §10.4).
    data_source: Literal["live", "fixtures"] = "live"
    fixtures_dir: Path | None = None
    # Data de referência da coleta ("hoje"). Só é aceita com data_source=fixtures, para o E2E
    # ser determinístico; em produção a referência é sempre a data corrente de São Paulo.
    collection_today: date | None = None
    # PRD-NF-02: coleta educada.
    http_requests_per_second: float = Field(default=1.0, gt=0, le=5)
    http_timeout_s: float = Field(default=60.0, gt=0)
    http_max_attempts: int = Field(default=3, ge=1, le=6)
    http_backoff_base_s: float = Field(default=2.0, ge=0)
    # Genérico: não identifica o usuário (PRD-NF-02).
    http_user_agent: str = "Mozilla/5.0 (compatible; VolLab/0.2; coleta local)"
    # Falhas transitórias seguidas (rede, 429, 403 do Cloudflare, 5xx) que interrompem a coleta.
    collection_max_consecutive_failures: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def _check_source(self) -> "Settings":
        if self.data_source == "fixtures" and self.fixtures_dir is None:
            raise ValueError("DATA_SOURCE=fixtures exige FIXTURES_DIR.")
        if self.collection_today is not None and self.data_source != "fixtures":
            raise ValueError("COLLECTION_TODAY só é aceita com DATA_SOURCE=fixtures.")
        return self

    @field_validator("database_url")
    @classmethod
    def _check_dsn(cls, value: SecretStr) -> SecretStr:
        try:
            PostgresDsn(value.get_secret_value())
        except ValueError:
            # Mensagem sem o valor: ele contém a senha.
            raise ValueError("DATABASE_URL inválida (esperado postgresql+psycopg://...).") from None
        return value

    def database_dsn(self) -> str:
        return self.database_url.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
