"""Fila de jobs em tabela Postgres (ADR-08).

A retirada usa `SELECT … FOR UPDATE SKIP LOCKED`: vários workers podem consumir a
mesma fila sem pegar o mesmo job. Jobs que ficaram `running` com um lock antigo
(worker morto) voltam para a fila em `requeue_stale`, o que torna a execução
retomável após reinício (PRD-NF-03).
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from vollab.db.models import Job, JobStatus

# Espera antes de tentar de novo: 30 s, 60 s, 120 s, ... (backoff exponencial, PRD-NF-02).
RETRY_BASE_DELAY = timedelta(seconds=30)


def enqueue(
    session: Session,
    *,
    user_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any] | None = None,
    max_attempts: int = 3,
) -> Job:
    job = Job(user_id=user_id, kind=kind, payload=payload or {}, max_attempts=max_attempts)
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session, *, worker_id: str) -> Job | None:
    """Retira o próximo job pronto e o marca como `running`. Faz commit para liberar o lock."""
    stmt = (
        select(Job)
        .where(Job.status == JobStatus.QUEUED, Job.run_after <= func.now())
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.scalars(stmt).first()
    if job is None:
        session.rollback()
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.locked_by = worker_id
    job.locked_at = func.now()
    session.commit()
    session.refresh(job)
    return job


def mark_succeeded(session: Session, job: Job) -> None:
    job.status = JobStatus.SUCCEEDED
    job.finished_at = func.now()
    job.last_error = None
    session.commit()


def mark_failed(session: Session, job: Job, error: str) -> None:
    """Registra a falha. Se ainda houver tentativas, volta para a fila com backoff."""
    job.last_error = error[:4000]
    job.locked_by = None
    job.locked_at = None
    if job.attempts < job.max_attempts:
        delay = RETRY_BASE_DELAY * (2 ** (job.attempts - 1))
        job.status = JobStatus.QUEUED
        job.run_after = func.now() + delay
    else:
        job.status = JobStatus.FAILED
        job.finished_at = func.now()
    session.commit()


def release(session: Session, job: Job) -> None:
    """Devolve à fila um job interrompido pelo worker, sem consumir a tentativa (JobInterruptedError)."""
    job.status = JobStatus.QUEUED
    job.attempts = max(job.attempts - 1, 0)
    job.locked_by = None
    job.locked_at = None
    job.run_after = func.now()
    session.commit()


def requeue_stale(session: Session, *, older_than: timedelta) -> int:
    """Devolve à fila os jobs `running` cujo lock é mais antigo que `older_than`.

    Um job travado que já esgotou as tentativas vai para `failed`. Retorna quantos voltaram à fila.
    """
    stale = (Job.status == JobStatus.RUNNING, Job.locked_at < func.now() - older_than)
    session.execute(
        update(Job)
        .where(*stale, Job.attempts >= Job.max_attempts)
        .values(
            status=JobStatus.FAILED,
            locked_by=None,
            locked_at=None,
            finished_at=func.now(),
            last_error="Worker interrompido durante a execução; tentativas esgotadas.",
        )
    )
    result = session.execute(
        update(Job)
        .where(*stale, Job.attempts < Job.max_attempts)
        .values(status=JobStatus.QUEUED, locked_by=None, locked_at=None, run_after=func.now())
    )
    session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]
