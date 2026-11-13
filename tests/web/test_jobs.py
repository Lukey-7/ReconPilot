"""The PostgreSQL job queue and the worker (Review Focus 3)."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from reconpilot_web import jobs
from reconpilot_web.models import Job


@pytest.fixture
def factory(clean_db, db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(jobs, "RETRY_DELAY", timedelta(0))


def _enqueue(factory, n: int = 1, kind: str = "test") -> list[int]:
    with factory() as session, session.begin():
        return [jobs.enqueue(session, kind, {"n": i}, None) for i in range(n)]


def _job(factory, job_id: int) -> Job:
    with factory() as session:
        return session.get(Job, job_id)


def test_enqueue_and_claim_oldest_first(factory):
    first, second = _enqueue(factory, 2)
    with factory() as session, session.begin():
        job = jobs.claim(session, "w1")
        assert job.id == first
        assert (job.status, job.attempts, job.locked_by) == ("running", 1, "w1")
        assert job.started_at is not None
    assert _job(factory, second).status == "queued"


def test_claim_returns_none_when_nothing_is_due(factory):
    (job_id,) = _enqueue(factory)
    with factory() as session, session.begin():
        session.execute(text("UPDATE jobs SET run_after = now() + interval '1 hour' WHERE id = :id"), {"id": job_id})
    with factory() as session, session.begin():
        assert jobs.claim(session, "w1") is None


def test_two_workers_never_claim_the_same_job(factory):
    ids = _enqueue(factory, 50)
    claimed: dict[str, list[int]] = {"a": [], "b": []}
    start = threading.Barrier(2)

    def worker(name: str) -> None:
        start.wait()
        while True:
            with factory() as session, session.begin():
                job = jobs.claim(session, name)
                if job is None:
                    return
                claimed[name].append(job.id)

    threads = [threading.Thread(target=worker, args=(name,)) for name in claimed]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    everything = claimed["a"] + claimed["b"]
    assert sorted(everything) == ids  # each job claimed exactly once
    with factory() as session:
        rows = session.execute(select(Job.status, Job.attempts)).all()
    assert {(s, a) for s, a in rows} == {("running", 1)}


def test_complete_records_result(factory):
    (job_id,) = _enqueue(factory)
    ran = []

    def handler(session, payload):
        ran.append(payload)
        return {"cases": 3}

    assert jobs.work_one(factory, "w1", {"test": handler}) == job_id
    job = _job(factory, job_id)
    assert ran == [{"n": 0}]
    assert (job.status, job.result, job.error, job.attempts) == ("done", {"cases": 3}, None, 1)
    assert job.finished_at is not None
    assert jobs.work_one(factory, "w1", {"test": handler}) is None


def test_handler_work_commits_with_the_job(factory):
    """The handler's writes and the job's ``done`` status are one transaction."""
    (job_id,) = _enqueue(factory)

    def handler(session, payload):
        jobs.enqueue(session, "follow-up", {}, None)
        return {}

    jobs.work_one(factory, "w1", {"test": handler})
    with factory() as session:
        kinds = session.execute(select(Job.kind, Job.status).order_by(Job.id)).all()
    assert [tuple(k) for k in kinds] == [("test", "done"), ("follow-up", "queued")]


def test_failure_retries_then_fails(factory, no_backoff):
    (job_id,) = _enqueue(factory)
    calls = []

    def handler(session, payload):
        jobs.enqueue(session, "should-vanish", {}, None)  # rolled back with the failure
        calls.append(1)
        raise ValueError("engine exploded")

    for attempt in (1, 2):
        assert jobs.work_one(factory, "w1", {"test": handler}) == job_id
        job = _job(factory, job_id)
        assert (job.status, job.attempts) == ("queued", attempt)
        assert job.error == "ValueError: engine exploded"

    assert jobs.work_one(factory, "w1", {"test": handler}) == job_id
    job = _job(factory, job_id)
    assert (job.status, job.attempts, job.max_attempts) == ("failed", 3, 3)
    assert job.error == "ValueError: engine exploded"
    assert job.finished_at is not None
    assert len(calls) == 3
    assert jobs.work_one(factory, "w1", {"test": handler}) is None  # never claimed again
    with factory() as session:
        assert session.execute(select(Job.kind)).scalars().all() == ["test"]  # nothing from any attempt kept


def test_retry_waits_for_the_back_off(factory):
    (job_id,) = _enqueue(factory)

    def handler(session, payload):
        raise RuntimeError("try later")

    jobs.work_one(factory, "w1", {"test": handler})
    with factory() as session:
        due_in = session.execute(
            text("SELECT extract(epoch FROM run_after - now()) FROM jobs WHERE id = :id"), {"id": job_id}
        ).scalar_one()
    assert 5 < float(due_in) <= 10  # 10 seconds times one attempt
    assert jobs.work_one(factory, "w1", {"test": handler}) is None


def test_failure_hook_is_told_when_the_job_gives_up(factory, no_backoff, monkeypatch):
    (job_id,) = _enqueue(factory, kind="hooked")
    seen = []
    monkeypatch.setitem(jobs.FAILURE_HOOKS, "hooked", lambda session, job, error, final: seen.append((error, final)))

    def handler(session, payload):
        raise KeyError("x")

    for _ in range(3):
        jobs.work_one(factory, "w1", {"hooked": handler})
    assert seen == [("KeyError: 'x'", False), ("KeyError: 'x'", False), ("KeyError: 'x'", True)]


def test_unknown_kind_fails_the_job(factory, no_backoff):
    (job_id,) = _enqueue(factory, kind="mystery")
    for _ in range(3):
        jobs.work_one(factory, "w1", {})
    job = _job(factory, job_id)
    assert job.status == "failed" and "no handler" in job.error


def test_abandoned_job_is_recovered_as_a_failed_attempt(factory):
    """A worker that dies leaves its job running; after the lease it is retried."""
    (job_id,) = _enqueue(factory)
    with factory() as session, session.begin():
        jobs.claim(session, "dead-worker")
    with factory() as session, session.begin():
        assert jobs.recover_stale(session) == []  # still within the lease
    with factory() as session, session.begin():
        session.execute(text("UPDATE jobs SET started_at = now() - interval '2 hours' WHERE id = :id"), {"id": job_id})
    with factory() as session, session.begin():
        assert jobs.recover_stale(session) == [job_id]
    job = _job(factory, job_id)
    assert job.status == "queued" and job.attempts == 1
    assert job.error == "The worker dead-worker stopped before finishing the job."


def test_run_worker_once_drains_the_queue(factory, settings):
    ids = _enqueue(factory, 3)
    seen = []
    done = jobs.run_worker(settings, once=True, handlers={"test": lambda s, p: seen.append(p["n"]) or {}})
    assert done == 3 and seen == [0, 1, 2]
    with factory() as session:
        assert set(session.execute(select(Job.status).where(Job.id.in_(ids))).scalars()) == {"done"}
