"""Fixtures comuns.

Testes de integração usam TEST_DATABASE_URL (um banco dedicado, que é zerado e migrado
no início da sessão). Sem a variável, eles são pulados localmente e FALHAM no CI.
Nenhum teste acessa a rede externa (B3, BCB, Yahoo).
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

# Unitários não tocam o banco, mas Settings exige DATABASE_URL: um valor inválido de propósito.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unit:unit@127.0.0.1:9/unit-tests-sem-banco")

ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
# Base URL dos TestClients: o guarda de Host só aceita hosts locais (PRD-NF-01).
LOCAL = "http://127.0.0.1:8000"


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
    # A sessão de testes zera o banco (downgrade base): nunca aponte para o banco real.
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.fail(
            f"TEST_DATABASE_URL deve apontar para um banco terminado em _test (recebido: {database!r})."
        )
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


@pytest.fixture(scope="session")
def app_engine(migrated_engine: Engine, database_url: str) -> Iterator[Engine]:
    """Conexões como o papel da aplicação (`vollab_app`, migration 0007): os testes exercitam o código
    com os mesmos privilégios da API e do worker."""
    from vollab.db.session import APP_ROLE, make_engine

    engine = make_engine(database_url, role=APP_ROLE)
    yield engine
    engine.dispose()


@pytest.fixture
def make_session(migrated_engine: Engine, app_engine: Engine) -> Iterator[sessionmaker[Session]]:
    yield sessionmaker(bind=app_engine, expire_on_commit=False)
    # config_versions é imutável (inclusive contra TRUNCATE). Só a limpeza de testes desliga os
    # triggers, com session_replication_role = replica (exige superusuário, como no compose e no CI).
    with migrated_engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(
            text(
                "TRUNCATE jobs, config_versions, collection_items, collection_runs, trades, daily_bars, "
                "option_daily_stats, series_adjustments, option_series, risk_free_rates, corporate_actions, "
                "raw_files, intraday_bars, intraday_sessions, realized_vols, implied_vols, "
                "option_daily_quotes, atm_term_structure, constant_maturity_vols, events, rv_forecasts, "
                "forecast_evaluations, forecast_evaluation_points, option_spread_estimates, positions, "
                "position_entries, manual_inputs, alerts, position_management "
                "RESTART IDENTITY CASCADE"
            )
        )
        # Universo inicial semeado pela migration 0003: volta ao estado original.
        conn.execute(text("DELETE FROM underlyings WHERE ticker NOT IN ('BOVA11', 'BBAS3', 'PETR4')"))
        conn.execute(text("UPDATE underlyings SET active = true"))


@pytest.fixture
def owner_session(migrated_engine: Engine, make_session: sessionmaker[Session]) -> Iterator[Session]:
    """Sessão como o dono do banco (sem SET ROLE): para testar os triggers por trás dos privilégios."""
    with Session(migrated_engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def session(make_session: sessionmaker[Session]) -> Iterator[Session]:
    with make_session() as s:
        yield s


@pytest.fixture
def api_client(make_session: sessionmaker[Session]) -> Iterator["TestClient"]:
    from fastapi.testclient import TestClient

    from vollab.api.app import create_app
    from vollab.db.session import get_session

    app = create_app()

    def _session() -> Iterator[Session]:
        with make_session() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield TestClient(app, base_url=LOCAL)


@pytest.fixture
def fixture_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Engine em modo de fixtures, com "hoje" = 20/11/2026 (D-1 = 19/11, último pregão das fixtures)."""
    from vollab.settings import get_settings

    monkeypatch.setenv("DATA_SOURCE", "fixtures")
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))
    monkeypatch.setenv("COLLECTION_TODAY", "2026-11-20")
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
