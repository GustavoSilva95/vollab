from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from vollab.db.models import FIXED_USER_ID, Job, JobStatus
from vollab.jobs import queue
from vollab.jobs.handlers import register
from vollab.jobs.worker import run_one

pytestmark = pytest.mark.integration


@register("test_fail")
def _always_fails(session: Session, payload: dict[str, object]) -> None:
    raise RuntimeError("falha simulada")


def _enqueue(session: Session, kind: str = "noop", **kwargs: int) -> Job:
    job = queue.enqueue(session, user_id=FIXED_USER_ID, kind=kind, **kwargs)  # type: ignore[arg-type]
    session.commit()
    return job


def test_noop_job_runs_to_success(session: Session) -> None:
    job = _enqueue(session)
    assert run_one(session, worker_id="w1") is True
    session.refresh(job)
    assert job.status is JobStatus.SUCCEEDED
    assert job.attempts == 1
    assert job.finished_at is not None
    assert run_one(session, worker_id="w1") is False


def test_skip_locked_never_hands_the_same_job_twice(make_session: sessionmaker[Session]) -> None:
    """ADR-08: um job travado por um worker é pulado pelos outros."""
    with make_session() as setup:
        first = _enqueue(setup)
        second = _enqueue(setup)

    with make_session() as holder, make_session() as other:
        locked = holder.scalars(select(Job).where(Job.id == first.id).with_for_update()).one()
        claimed = queue.claim_next(other, worker_id="w2")
        assert claimed is not None
        assert claimed.id == second.id
        assert locked.id == first.id
        holder.rollback()


def _status(session: Session, job: Job) -> JobStatus:
    session.refresh(job)
    return job.status


def test_failure_is_retried_with_backoff_then_fails(session: Session) -> None:
    job = _enqueue(session, "test_fail", max_attempts=2)

    run_one(session, worker_id="w1")
    assert _status(session, job) is JobStatus.QUEUED
    assert job.attempts == 1
    assert job.last_error == "RuntimeError"  # B-5: sem a mensagem
    # Backoff: ainda não está pronto para rodar de novo.
    assert run_one(session, worker_id="w1") is False

    session.execute(text("UPDATE jobs SET run_after = now() WHERE id = :id"), {"id": job.id})
    session.commit()
    run_one(session, worker_id="w1")
    assert _status(session, job) is JobStatus.FAILED
    assert job.attempts == 2


def test_unknown_kind_fails_without_retry(session: Session) -> None:
    job = _enqueue(session, "nao_existe")
    run_one(session, worker_id="w1")
    session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None
    assert "desconhecido" in job.last_error


def test_stale_running_jobs_are_requeued(session: Session) -> None:
    """PRD-NF-03: um worker morto no meio do job não perde o trabalho."""
    retryable = _enqueue(session)
    exhausted = _enqueue(session, max_attempts=1)
    for _ in (retryable, exhausted):
        queue.claim_next(session, worker_id="morto")
    session.execute(text("UPDATE jobs SET locked_at = now() - interval '1 hour'"))
    session.commit()

    assert queue.requeue_stale(session, older_than=timedelta(minutes=10)) == 1
    session.refresh(retryable)
    session.refresh(exhausted)
    assert retryable.status is JobStatus.QUEUED
    assert retryable.locked_by is None
    assert exhausted.status is JobStatus.FAILED
