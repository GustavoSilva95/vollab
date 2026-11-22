from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from vollab.settings import get_settings


def make_engine(url: str) -> Engine:
    # connect_timeout curto: o /health responde "unavailable" em vez de travar.
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine(get_settings().database_dsn())


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão por requisição."""
    with get_sessionmaker()() as session:
        yield session
