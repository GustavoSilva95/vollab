"""Registro de tipos de job. Cada etapa registra os seus (ex.: coleta na Etapa 2)."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

JobHandler = Callable[[Session, dict[str, Any]], None]

_HANDLERS: dict[str, JobHandler] = {}


def register(kind: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(fn: JobHandler) -> JobHandler:
        if kind in _HANDLERS:
            raise ValueError(f"Tipo de job já registrado: {kind}")
        _HANDLERS[kind] = fn
        return fn

    return decorator


def get_handler(kind: str) -> JobHandler | None:
    return _HANDLERS.get(kind)


@register("noop")
def _noop(session: Session, payload: dict[str, Any]) -> None:
    """Job de diagnóstico: não faz nada. Usado para verificar a fila de ponta a ponta."""
