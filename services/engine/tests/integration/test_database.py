from collections.abc import Iterator

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import LOCAL, alembic_config
from vollab.api.app import create_app
from vollab.db.config_store import create_config_version, current_config_version
from vollab.db.models import FIXED_USER_ID, ConfigVersion, User
from vollab.db.session import get_session

pytestmark = pytest.mark.integration


def test_migration_creates_foundation_tables(migrated_engine: Engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())
    assert {"users", "config_versions", "jobs", "alembic_version"} <= tables


def test_downgrade_and_upgrade_roundtrip(migrated_engine: Engine, database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    assert "users" not in inspect(migrated_engine).get_table_names()
    command.upgrade(cfg, "head")
    assert "users" in inspect(migrated_engine).get_table_names()


def test_fixed_user_exists(session: Session) -> None:
    """ADR-13: usuário fixo criado na carga inicial."""
    user = session.get(User, FIXED_USER_ID)
    assert user is not None


def test_config_versions_current_is_latest(session: Session) -> None:
    assert current_config_version(session, user_id=FIXED_USER_ID) is None
    create_config_version(session, user_id=FIXED_USER_ID, params={"min_trades": 10})
    second = create_config_version(session, user_id=FIXED_USER_ID, params={"min_trades": 20}, note="QA-06")
    session.commit()
    current = current_config_version(session, user_id=FIXED_USER_ID)
    assert current is not None
    assert current.id == second.id
    assert current.params == {"min_trades": 20}


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_config_versions_are_immutable(session: Session, operation: str) -> None:
    """PRD §5.3: editar cria versão nova; o banco recusa UPDATE e DELETE."""
    version = create_config_version(session, user_id=FIXED_USER_ID, params={"a": 1})
    session.commit()
    if operation == "update":
        version.params = {"a": 2}
    else:
        session.delete(version)
    with pytest.raises(DBAPIError, match="imutável"):
        session.commit()
    session.rollback()
    stored = session.scalars(select(ConfigVersion)).one()
    assert stored.params == {"a": 1}


def test_config_versions_reject_truncate(session: Session) -> None:
    create_config_version(session, user_id=FIXED_USER_ID, params={"a": 1})
    session.commit()
    with pytest.raises(DBAPIError, match="imutável"):
        session.execute(text("TRUNCATE config_versions"))
    session.rollback()
    assert session.scalars(select(ConfigVersion)).one().params == {"a": 1}


@pytest.fixture
def api_client(make_session: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app()

    def _session() -> Iterator[Session]:
        with make_session() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    yield TestClient(app, base_url=LOCAL)


def test_health_ok_with_database(api_client: TestClient) -> None:
    body = api_client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
