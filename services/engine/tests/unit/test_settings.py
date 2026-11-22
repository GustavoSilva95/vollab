import pytest
from pydantic import ValidationError

from vollab.settings import Settings


def test_engine_listens_on_loopback_by_default() -> None:
    """PRD-NF-01: o engine escuta só em 127.0.0.1."""
    settings = Settings(database_url="postgresql+psycopg://u:p@127.0.0.1:5432/db")
    assert settings.engine_host == "127.0.0.1"


def test_database_url_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRD-NF-09: nenhum segredo com valor padrão no código."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_is_secret() -> None:
    """B-5: a senha da DSN não aparece em repr nem em mensagens de erro."""
    settings = Settings(database_url="postgresql+psycopg://u:segredo@127.0.0.1:5432/db")
    assert "segredo" not in repr(settings)
    assert settings.database_dsn().endswith("@127.0.0.1:5432/db")
    with pytest.raises(ValidationError) as err:
        Settings(database_url="mysql://u:segredo@x/db")
    assert "segredo" not in str(err.value)


def test_fixture_mode_requires_dir_and_today_only_with_fixtures() -> None:
    url = "postgresql+psycopg://u:p@127.0.0.1:5432/db"
    with pytest.raises(ValidationError):
        Settings(database_url=url, data_source="fixtures")
    with pytest.raises(ValidationError):
        Settings(database_url=url, collection_today="2026-11-19")
    ok = Settings(database_url=url, data_source="fixtures", fixtures_dir="fx", collection_today="2026-11-19")
    assert ok.collection_today is not None
