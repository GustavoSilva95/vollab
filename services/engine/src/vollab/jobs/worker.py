"""Processo worker (ADR-08): consome a fila `jobs` até receber SIGTERM/SIGINT.

Uso: `python -m vollab.jobs.worker`
"""

import os
import signal
import socket
import threading
from datetime import timedelta
from types import FrameType

import structlog
from sqlalchemy.orm import Session, sessionmaker

import vollab.analytics.crisis  # registra a medição dos cenários de crise (Etapa 7)
import vollab.analytics.forecasting  # registra o job de previsão (Etapa 4)
import vollab.analytics.journal  # registra a marcação D-1 e a atribuição (Etapa 7)
import vollab.analytics.recompute  # registra o job de recálculo de volatilidade
import vollab.collection.runner  # noqa: F401  (registra o job de coleta)
from vollab.db.session import get_sessionmaker
from vollab.jobs import queue
from vollab.jobs.control import JobInterruptedError, stop_event
from vollab.jobs.handlers import get_handler
from vollab.log import configure_logging
from vollab.settings import get_settings

log = structlog.get_logger("vollab.worker")


def run_one(session: Session, *, worker_id: str) -> bool:
    """Executa no máximo um job. Retorna `True` se havia job para executar."""
    job = queue.claim_next(session, worker_id=worker_id)
    if job is None:
        return False
    bound = log.bind(job_id=job.id, kind=job.kind, attempt=job.attempts)
    handler = get_handler(job.kind)
    if handler is None:
        job.attempts = job.max_attempts  # tipo desconhecido não adianta repetir
        queue.mark_failed(session, job, f"Tipo de job desconhecido: {job.kind}")
        bound.error("job.unknown_kind")
        return True
    try:
        handler(session, dict(job.payload))
    except JobInterruptedError:
        session.rollback()
        queue.release(session, job)
        bound.info("job.interrupted")
    except Exception as exc:  # erro do job não derruba o worker (PRD-NF-10)
        session.rollback()
        # B-5: só o tipo do erro vai para `last_error` (a mensagem pode trazer dados da fonte ou do ambiente).
        queue.mark_failed(session, job, type(exc).__name__)
        bound.exception("job.failed")
    else:
        queue.mark_succeeded(session, job)
        bound.info("job.succeeded")
    return True


def run_forever(make_session: sessionmaker[Session], *, stop: threading.Event) -> None:
    settings = get_settings()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stale_after = timedelta(seconds=settings.worker_stale_lock_s)
    log.info("worker.started", worker_id=worker_id, engine_version=settings.engine_version)
    with make_session() as session:
        requeued = queue.requeue_stale(session, older_than=stale_after)
        if requeued:
            log.warning("worker.requeued_stale", count=requeued)
    while not stop.is_set():
        try:
            with make_session() as session:
                worked = run_one(session, worker_id=worker_id)
        except Exception:  # banco fora do ar etc.: espera e tenta de novo
            log.exception("worker.loop_error")
            worked = False
        if not worked:
            stop.wait(settings.worker_poll_interval_s)
    log.info("worker.stopped", worker_id=worker_id)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    stop = stop_event()

    def _handle(signum: int, _frame: FrameType | None) -> None:
        log.info("worker.signal", signal=signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    run_forever(get_sessionmaker(), stop=stop)


if __name__ == "__main__":
    main()
