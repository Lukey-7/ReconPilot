"""A small job queue in PostgreSQL, and the worker that runs it.

Runs go through the queue because a run with the AI switched on can take
minutes (spec 4.3). A job is a row in ``jobs``:

* ``enqueue`` adds a ``queued`` job in the caller's transaction, so a job exists
  exactly when the request that asked for it commits;
* ``claim`` takes the oldest ``queued`` job whose ``run_after`` has passed, with
  ``FOR UPDATE SKIP LOCKED`` so two workers never take the same job, marks it
  ``running`` and counts the attempt;
* the job's handler then runs in a **new** transaction, and ``complete`` is
  written in that same transaction, so the handler's work and the job's ``done``
  status commit together or not at all;
* if the handler raises, its transaction is rolled back (nothing it wrote is
  kept) and ``fail`` runs in a fresh transaction: the job goes back to
  ``queued`` with a back-off (``RETRY_DELAY`` times the attempts so far) until it
  has had ``max_attempts`` attempts, then it is ``failed`` with the error;
* if a worker dies mid-job, the job stays ``running``; once it has been running
  longer than ``JOB_LEASE``, any worker's ``recover_stale`` treats it as a failed
  attempt in the same way.

Handlers are registered by kind in ``HANDLERS``. Each receives an open session
and the job's payload and returns the result dict. A kind may also register a
failure hook in ``FAILURE_HOOKS``, called in ``fail``'s transaction after every
failed attempt (``final`` is true once the job will not be retried), so for
example a day can be marked ``failed`` when its run gives up.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import traceback
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from reconpilot_web.models import Job

log = logging.getLogger(__name__)

Handler = Callable[[Session, dict], dict]
FailureHook = Callable[[Session, Job, str, bool], None]

HANDLERS: dict[str, Handler] = {}
FAILURE_HOOKS: dict[str, FailureHook] = {}

RETRY_DELAY = timedelta(seconds=10)  # back-off per attempt already made
JOB_LEASE = timedelta(minutes=30)  # a job running longer than this is presumed abandoned
POLL_INTERVAL = 1.0  # seconds a worker waits when the queue is empty
MAX_ERROR_CHARS = 4000


def register(kind: str, handler: Handler, on_failure: FailureHook | None = None) -> None:
    """Make ``handler`` (and optionally a failure hook) the one for jobs of ``kind``."""
    HANDLERS[kind] = handler
    if on_failure is not None:
        FAILURE_HOOKS[kind] = on_failure


def default_handlers() -> dict[str, Handler]:
    """The registered handlers, after importing the modules that register them."""
    from reconpilot_web import runner  # noqa: F401  (registers "run_day")

    return dict(HANDLERS)


def new_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- queue operations


def enqueue(session: Session, kind: str, payload: dict, created_by: int | None) -> int:
    """Add a queued job in the caller's transaction and return its id."""
    job = Job(kind=kind, payload=payload, status="queued", created_by=created_by)
    session.add(job)
    session.flush()
    return job.id


def claim(session: Session, worker_id: str) -> Job | None:
    """Take the oldest queued job that is due, mark it running and count the attempt.

    The caller commits; until then the row stays locked and other workers skip it.
    """
    job = session.execute(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= func.now())
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_by = worker_id
    job.started_at = func.now()
    job.finished_at = None
    session.flush()
    session.refresh(job)
    return job


def complete(session: Session, job_id: int, result: dict) -> None:
    """Mark a job done with its result, in the caller's transaction."""
    job = session.get(Job, job_id, with_for_update=True)
    if job is None:
        raise LookupError(f"no job {job_id}")
    job.status = "done"
    job.result = result
    job.error = None
    job.finished_at = func.now()
    session.flush()


def fail(session: Session, job_id: int, error: str) -> Job:
    """Record a failed attempt: back to ``queued`` with a back-off, or ``failed`` after the last.

    Calls the kind's failure hook, if any, in the same transaction. Returns the job.
    """
    job = session.get(Job, job_id, with_for_update=True)
    if job is None:
        raise LookupError(f"no job {job_id}")
    error = (error or "unknown error")[:MAX_ERROR_CHARS]
    job.error = error
    final = job.attempts >= job.max_attempts
    if final:
        job.status = "failed"
        job.finished_at = func.now()
    else:
        job.status = "queued"
        job.run_after = func.now() + RETRY_DELAY * max(job.attempts, 1)
    session.flush()
    hook = FAILURE_HOOKS.get(job.kind)
    if hook is not None:
        hook(session, job, error, final)
    session.refresh(job)
    return job


def recover_stale(session: Session, lease: timedelta | None = None) -> list[int]:
    """Treat jobs left ``running`` longer than ``lease`` (a dead worker's) as failed attempts.

    Returns the ids recovered. The caller commits.
    """
    lease = JOB_LEASE if lease is None else lease
    stale = session.execute(
        select(Job)
        .where(Job.status == "running", Job.started_at < func.now() - lease)
        .order_by(Job.id)
        .with_for_update(skip_locked=True)
    ).scalars().all()
    for job in stale:
        log.warning("job %s (%s) was abandoned by %s; recording a failed attempt", job.id, job.kind, job.locked_by)
        who = f" {job.locked_by}" if job.locked_by else ""
        fail(session, job.id, f"The worker{who} stopped before finishing the job.")
    return [job.id for job in stale]


def job_payload(job: Job) -> dict[str, Any]:
    """A job as the API reports it."""
    def ts(value):
        return value.isoformat() if value is not None else None

    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error": job.error,
        "result": job.result,
        "created_at": ts(job.created_at),
        "started_at": ts(job.started_at),
        "finished_at": ts(job.finished_at),
    }


# --------------------------------------------------------------------------- worker


def _error_text(exc: BaseException) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def work_one(
    session_factory: sessionmaker,
    worker_id: str,
    handlers: dict[str, Handler] | None = None,
) -> int | None:
    """Claim and run one job. Returns its id, or ``None`` when no job is due."""
    handlers = default_handlers() if handlers is None else handlers
    with session_factory() as session, session.begin():
        job = claim(session, worker_id)
        if job is None:
            return None
        job_id, kind, payload = job.id, job.kind, dict(job.payload or {})

    try:
        handler = handlers.get(kind)
        if handler is None:
            raise LookupError(f"no handler for jobs of kind {kind!r}")
        with session_factory() as session, session.begin():
            result = handler(session, payload)
            complete(session, job_id, result if isinstance(result, dict) else {"result": result})
    except Exception as exc:  # the handler's transaction has been rolled back
        log.error("job %s (%s) failed: %s\n%s", job_id, kind, exc, traceback.format_exc())
        with session_factory() as session, session.begin():
            fail(session, job_id, _error_text(exc))
    return job_id


def run_worker(
    settings,
    once: bool = False,
    handlers: dict[str, Callable] | None = None,
    *,
    stop: threading.Event | None = None,
    poll_interval: float = POLL_INTERVAL,
    worker_id: str | None = None,
) -> int:
    """Run jobs until stopped (``stop`` set, or Ctrl+C). Returns the number of jobs run.

    With ``once``, run every job that is due and return when the queue is empty.
    """
    from reconpilot_web import db
    from reconpilot_web.cli import database_urls
    from reconpilot_web.models import assert_instance_mode

    handlers = default_handlers() if handlers is None else handlers
    worker_id = worker_id or new_worker_id()
    url, _ = database_urls(settings)
    engine = db.make_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    done = 0
    try:
        with factory() as session:
            assert_instance_mode(session, settings.mode)
        log.info("worker %s started", worker_id)
        while stop is None or not stop.is_set():
            with factory() as session, session.begin():
                recover_stale(session)
            job_id = work_one(factory, worker_id, handlers)
            if job_id is not None:
                done += 1
                continue
            if once:
                break
            if stop is not None:
                stop.wait(poll_interval)
            else:
                threading.Event().wait(poll_interval)
    finally:
        engine.dispose()
    return done
