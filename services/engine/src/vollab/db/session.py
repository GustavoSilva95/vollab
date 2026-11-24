from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from vollab.settings import get_settings

# Papel da aplicação criado pela migration 0007 (backlog M-2 b): sem DDL, sem TRUNCATE e sem
# UPDATE/DELETE nas tabelas imutáveis. As migrations rodam com o dono do banco, sem SET ROLE.
APP_ROLE = "vollab_app"


def make_engine(url: str, *, role: str | None = None) -> Engine:
    # connect_timeout curto: o /health responde "unavailable" em vez de travar.
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    if role is not None:
        if not role.replace("_", "").isalnum():
            raise ValueError("Nome de papel inválido.")

        @event.listens_for(engine, "connect")
        def _set_role(dbapi_connection: Any, _record: Any) -> None:
            # Defesa em profundidade contra erro do próprio app (não contra credencial vazada: o
            # usuário da conexão continua sendo o dono). O nome foi validado acima.
            with dbapi_connection.cursor() as cur:
                cur.execute(f"SET ROLE {role}")
            dbapi_connection.commit()

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return make_engine(settings.database_dsn(), role=settings.database_role or None)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão por requisição."""
    with get_sessionmaker()() as session:
        yield session
