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
