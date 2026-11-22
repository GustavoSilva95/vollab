"""Sinal de parada do worker visível para jobs longos (ex.: a carga inicial de ~5 h).

O worker liga o evento ao receber SIGTERM/SIGINT. Um job longo consulta `stop_requested()`
entre itens e levanta `JobInterruptedError`; o worker devolve o job à fila sem gastar uma
tentativa, e a execução continua quando o worker voltar (PRD-NF-03).
"""

import threading

_STOP = threading.Event()


class JobInterruptedError(Exception):
    """O job parou a pedido do worker e deve voltar à fila sem contar tentativa."""


def request_stop() -> None:
    _STOP.set()


def stop_requested() -> bool:
    return _STOP.is_set()


def stop_event() -> threading.Event:
    return _STOP
