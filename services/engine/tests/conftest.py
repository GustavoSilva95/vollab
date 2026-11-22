"""Fixtures comuns.

Testes de integração usam TEST_DATABASE_URL (um banco dedicado, que é zerado e migrado
no início da sessão). Sem a variável, eles são pulados localmente e FALHAM no CI.
Nenhum teste acessa a rede externa (B3, BCB, Yahoo).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

# Unitários não tocam o banco, mas Settings exige DATABASE_URL: um valor inválido de propósito.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unit:unit@127.0.0.1:9/unit-tests-sem-banco")

ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ENGINE_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI"):
            pytest.fail("TEST_DATABASE_URL é obrigatória no CI para os testes de integração.")
        pytest.skip("TEST_DATABASE_URL não definida: testes de integração pulados.")
    return url


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    from vollab.db.session import make_engine

    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = make_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def make_session(migrated_engine: Engine) -> Iterator[sessionmaker[Session]]:
    yield sessionmaker(bind=migrated_engine, expire_on_commit=False)
    # TRUNCATE não dispara os triggers de linha que tornam config_versions imutável.
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE jobs, config_versions RESTART IDENTITY"))


@pytest.fixture
def session(make_session: sessionmaker[Session]) -> Iterator[Session]:
    with make_session() as s:
        yield s
