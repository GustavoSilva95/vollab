import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.conftest import alembic_config
from vollab.db.config_store import create_config_version, current_config_version
from vollab.db.models import FIXED_USER_ID, ConfigVersion, User

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
def test_config_versions_are_immutable(owner_session: Session, operation: str) -> None:
    """PRD §5.3: editar cria versão nova; o banco recusa UPDATE e DELETE (trigger, mesmo para o dono)."""
    session = owner_session
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


def test_config_versions_reject_truncate(owner_session: Session) -> None:
    session = owner_session
    create_config_version(session, user_id=FIXED_USER_ID, params={"a": 1})
    session.commit()
    # CASCADE: desde a Etapa 2, collection_runs referencia config_versions; o trigger ainda barra.
    with pytest.raises(DBAPIError, match="imutável"):
        session.execute(text("TRUNCATE config_versions CASCADE"))
    session.rollback()
    assert session.scalars(select(ConfigVersion)).one().params == {"a": 1}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE config_versions SET note = 'x'",
        "DELETE FROM config_versions",
        "TRUNCATE jobs",
        "CREATE TABLE intrusa (id int)",
        "DELETE FROM alembic_version",
        "UPDATE positions SET lots = 2",
        "DELETE FROM position_entries",
        "DELETE FROM manual_inputs",
    ],
)
def test_app_role_lacks_ddl_and_mutation_of_immutable_tables(session: Session, statement: str) -> None:
    """Backlog M-2 (b), migration 0007: o papel da aplicação não tem DDL, TRUNCATE nem UPDATE/DELETE
    nas tabelas imutáveis (antes até de chegar ao trigger)."""
    assert session.execute(text("SELECT current_user")).scalar() == "vollab_app"
    with pytest.raises(DBAPIError, match=r"permission denied|permissão negada"):
        session.execute(text(statement))
    session.rollback()


def test_app_role_creates_trades_partition_through_function(session: Session) -> None:
    from datetime import date

    from vollab.collection.ingest import ensure_trades_partition

    ensure_trades_partition(session, date(2031, 3, 17))
    ensure_trades_partition(session, date(2031, 3, 1))  # idempotente
    session.commit()
    name = session.execute(
        text("SELECT relname FROM pg_class WHERE relname = 'trades_y2031m03' AND relispartition")
    ).scalar()
    assert name == "trades_y2031m03"


def test_health_ok_with_database(api_client: TestClient) -> None:
    body = api_client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
