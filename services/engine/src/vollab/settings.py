"""Configuração por variáveis de ambiente (ADR-14, PRD-NF-09).

Nenhum segredo tem valor padrão: a URL do banco vem do ambiente (`.env` fora do git).
"""

from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: PostgresDsn = Field(
        description="URL SQLAlchemy do Postgres, com o driver psycopg (postgresql+psycopg://...).",
    )
    # PRD-NF-01: só escuta na interface local. Dentro do container o compose
    # sobrescreve para 0.0.0.0 e publica a porta apenas em 127.0.0.1 do host.
    engine_host: str = "127.0.0.1"
    engine_port: int = 8000
    # Versão gravada no retrato da decisão (PRD §5.4): git sha do build.
    engine_version: str = "dev"
    log_level: str = "INFO"
    log_json: bool = False
    # Worker (ADR-08)
    worker_poll_interval_s: float = Field(default=1.0, gt=0)
    worker_stale_lock_s: float = Field(default=600.0, gt=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
