"""Running uploaded days through the engine: persistence, carrying, failures, re-runs and the AI switch."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from reconpilot.matching import carry_forward
from reconpilot.models import Category
from reconpilot.pipeline import run_day as engine_run_day
from reconpilot.storage import read_day
from reconpilot_web import jobs, runner
from reconpilot_web.auditlog import DbAuditLog, verify_chain
from reconpilot_web.models import (
    AICacheEntry,
    BreakRow,
    BusinessDay,
    CaseRow,
    CaseSnapshot,
    Decision,
    Job,
    OpenItem,
    User,
)
from reconpilot_web.validation import FILE_KINDS

from .conftest import FUND_CODE, FUND_START
from .test_upload import upload

DAY1, DAY2 = FUND_START, date(2026, 11, 10)
TIMING_CASE = "EX-20261109-001"  # JP0000637983: booked trade the custodian settles a day late
DIVIDEND_CASE = "EX-20261109-004"  # US0000319391: dividend paid by the custodian, not booked
DIVIDEND_SECURITY = "US0000319391"


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(jobs, "RETRY_DELAY", timedelta(0))


def start_run(client, as_of: date = DAY1):
    return client.post(f"/api/funds/{FUND_CODE}/days/{as_of}/run")


def work(factory) -> int | None:
    """Run the next due job the way the worker does."""
    return jobs.work_one(factory, "test-worker")


def upload_and_run(client, factory, files, as_of: date = DAY1) -> int:
    assert upload(client, files, as_of=as_of).json()["status"] == "validated"
    response = start_run(client, as_of)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert work(factory) == job_id
    return job_id


def sign_off(db_session, fund, as_of: date) -> None:
    """Mark a day signed off directly (sign-off has its own module and tests)."""
    db_session.expire_all()
    day = db_session.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of == as_of)
    ).scalar_one()
    day.status = "signed_off"
    db_session.commit()


def actions(db_session) -> list[str]:
    db_session.expire_all()
    return [e["action"] for e in DbAuditLog(db_session).entries()]


def engine_days(tmp_path, day_files, n: int):
    """The command line's path through the same files: read_day, carry items and cases, run_day."""
    results, prev = [], None
    for i in range(n):
        folder = tmp_path / f"day{i}"
        folder.mkdir()
        for kind, content in day_files[i].items():
            (folder / FILE_KINDS[kind]).write_bytes(content)
        day = read_day(folder)
        if prev is not None:
            day.carried_book_items, day.carried_custodian_lines = carry_forward(prev.recon, prev.day)
        prev = engine_run_day(day, prev.open_cases if prev else [])
        results.append(prev)
    return results


def without_line(content: bytes, needle: str) -> bytes:
    lines = content.decode("utf-8").splitlines(keepends=True)
    return "".join(line for line in lines if needle not in line).encode("utf-8")


class FakeClient:
    provider = "fake"
    effort = "medium"
    model = "fake-1"

    def __init__(self):
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        evidence = json.loads(user.split("\n\n", 1)[1])
        return json.dumps({
            "category": evidence["rule_based_suggestion"]["category"],
            "confidence": 0.8,
            "explanation": "The evidence supports the rule-based cause.",
            "investigation_steps": ["Compare the book and custodian records.", "Ask the custodian to confirm."],
            "custodian_query": "Subject: Break\n\nPlease confirm.",
        })


# --------------------------------------------------------------------------- a first run


def test_run_creates_cases_and_snapshots(make_client, users, fund, day_files, factory, db_session, tmp_path):
    analyst = make_client("analyst1")
    assert upload(analyst, day_files[0]).json()["status"] == "validated"
    response = start_run(analyst)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    day = analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").json()
    assert day["status"] == "running" and day["job"]["status"] == "queued" and day["job"]["id"] == job_id
    assert analyst.get(f"/api/jobs/{job_id}").json()["status"] == "queued"

    assert work(factory) == job_id
    job = analyst.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done" and job["attempts"] == 1 and job["error"] is None
    assert job["result"]["open_cases"] == 4 and job["result"]["new_cases"] == 4

    expected = engine_days(tmp_path, day_files, 1)[0]
    cases = db_session.execute(select(CaseRow).order_by(CaseRow.case_id)).scalars().all()
    assert [(c.case_id, c.security_id, c.category) for c in cases] == sorted(
        (c.case_id, c.security_id, c.category.value) for c in expected.open_cases
    )
    by_id = {c.case_id: c for c in expected.open_cases}
    for row in cases:
        want = by_id[row.case_id]
        assert (row.nav_impact, row.material, row.status, row.version) == (want.nav_impact, want.material, "PENDING", 1)
        assert row.last_as_of == DAY1 and row.first_seen == DAY1 and row.cleared_on is None
        assert row.data["case_id"] == row.case_id

    snaps = db_session.execute(select(CaseSnapshot)).scalars().all()
    assert {(s.case_id, s.as_of, s.is_open) for s in snaps} == {(c, DAY1, True) for c in by_id}
    breaks = db_session.execute(select(BreakRow)).scalars().all()
    assert len(breaks) == len(expected.recon.breaks)
    assert {b.case_id for b in breaks} == set(by_id)
    items = db_session.execute(select(OpenItem)).scalars().all()
    book, cust = carry_forward(expected.recon, expected.day)
    assert len(items) == len(book) + len(cust)
    timing_item = next(i for i in items if i.side == "book" and i.security_id == "JP0000637983")
    assert timing_item.data["trade"]["trade_id"] == timing_item.reference  # the trade travels with the item

    day = analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").json()
    assert day["status"] == "ready" and day["error"] is None and day["run_by"] == "analyst1"
    assert day["nav"]["nav_per_share"] == expected.nav.nav_per_share
    assert day["nav"]["nav"] == expected.nav.nav
    assert [(c["name"], c["status"]) for c in day["checks"]] == [(c.name, c.status) for c in expected.checks]
    assert day["summary"]["ai"] == {"enabled": False, "available": False, "provider": None, "model": None,
                                    "disagreements": 0}

    log = actions(db_session)
    assert log[log.index("RUN_STARTED"):] == ["RUN_STARTED", "CASES_RAISED", "RUN_FINISHED"]
    assert verify_chain(db_session) == (True, None)


def test_bom_and_crlf_files_run_like_any_other(make_client, users, fund, day_files, factory, db_session):
    """Review focus 2: Excel's byte-order mark and CRLF line endings reach the engine harmlessly."""
    excel = {
        kind: b"\xef\xbb\xbf" + content.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        for kind, content in day_files[0].items()
    }
    upload_and_run(make_client("analyst1"), factory, excel)
    assert db_session.query(CaseRow).count() == 4


def test_second_day_carries_cases_and_items(make_client, users, fund, day_files, factory, db_session, tmp_path):
    analyst = make_client("analyst1")
    upload_and_run(analyst, factory, day_files[0])

    # The next day cannot be run (or even loaded) until this one is signed off.
    assert upload(analyst, day_files[1], as_of=DAY2).status_code == 409
    sign_off(db_session, fund, DAY1)
    upload_and_run(analyst, factory, day_files[1], as_of=DAY2)

    expected = engine_days(tmp_path, day_files, 2)[1]
    db_session.expire_all()
    timing = db_session.get(CaseRow, (fund.id, TIMING_CASE))
    assert timing.cleared_on == DAY2 and timing.resolved_category == Category.TIMING.value
    assert timing.version == 2 and timing.last_as_of == DAY2
    snap = db_session.get(CaseSnapshot, (fund.id, TIMING_CASE, DAY2))
    assert snap.is_open is False and snap.data["resolved_category"] == "TIMING"

    open_day2 = db_session.execute(
        select(CaseSnapshot).where(CaseSnapshot.as_of == DAY2, CaseSnapshot.is_open.is_(True))
    ).scalars().all()
    assert sorted((s.case_id, s.category, s.nav_impact, s.age_days) for s in open_day2) == sorted(
        (c.case_id, c.category.value, c.nav_impact, c.age_days) for c in expected.open_cases
    )
    carried = db_session.get(CaseRow, (fund.id, DIVIDEND_CASE))
    assert carried.first_seen == DAY1 and carried.last_as_of == DAY2 and carried.age_days == 1

    day = analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY2}").json()
    assert day["nav"]["nav_per_share"] == expected.nav.nav_per_share
    assert day["summary"]["cleared_today"] == [TIMING_CASE]
    assert day["summary"]["carried_cases"] == 4 and day["summary"]["previous_day"] == str(DAY1)
    assert "CASE_AUTO_CLEARED" in actions(db_session)


# --------------------------------------------------------------------------- failures


@pytest.mark.parametrize("where", ["engine", "persist"])
def test_engine_error_rolls_back_everything(make_client, users, fund, day_files, factory, db_session,
                                            monkeypatch, no_backoff, where):
    """Review focus 3: a run that raises keeps nothing, is retried three times, then the day fails."""
    real = runner.run_day if where == "engine" else runner._persist

    def explode(*args, **kwargs):
        real(*args, **kwargs)  # do the real work (audit entries, rows) first, then fail
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(runner, "run_day" if where == "engine" else "_persist", explode)
    analyst = make_client("analyst1")
    assert upload(analyst, day_files[0]).json()["status"] == "validated"
    job_id = start_run(analyst).json()["job_id"]

    for attempt in (1, 2, 3):
        assert work(factory) == job_id
        day = analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").json()
        assert day["status"] == ("running" if attempt < 3 else "failed")
    assert work(factory) is None

    job = analyst.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["attempts"] == 3 and job["error"] == "RuntimeError: disk on fire"
    day = analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").json()
    assert day["error"] == "RuntimeError: disk on fire" and day["nav"] is None

    for table in (CaseRow, CaseSnapshot, BreakRow, OpenItem):
        assert db_session.query(table).count() == 0
    log = actions(db_session)
    assert log[log.index("RUN_STARTED"):] == ["RUN_STARTED", "RUN_FAILED", "RUN_FAILED", "RUN_FAILED"]
    failed = [e["payload"] for e in DbAuditLog(db_session).entries() if e["action"] == "RUN_FAILED"]
    assert [(p["attempt"], p["will_retry"]) for p in failed] == [(1, True), (2, True), (3, False)]
    assert verify_chain(db_session) == (True, None)

    # A failed day can be run again once the fault is fixed.
    monkeypatch.undo()
    assert start_run(analyst).status_code == 202
    work(factory)
    assert analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").json()["status"] == "ready"
    assert db_session.query(CaseRow).count() == 4


# --------------------------------------------------------------------------- who may run what, and when


def test_run_refused_when_not_runnable(make_client, users, fund, day_files, factory, db_session):
    analyst = make_client("analyst1")
    assert start_run(analyst).status_code == 404  # nothing uploaded
    bad = {k: v for k, v in day_files[0].items() if k != "positions"}
    assert upload(analyst, bad).json()["status"] == "uploaded"
    response = start_run(analyst)
    assert response.status_code == 409 and "validation errors" in response.json()["detail"]

    assert upload(analyst, {"positions": day_files[0]["positions"]}).json()["status"] == "validated"
    assert make_client("viewer1").post(f"/api/funds/{FUND_CODE}/days/{DAY1}/run").status_code == 403
    assert start_run(analyst).status_code == 202
    response = start_run(make_client("approver1"))
    assert response.status_code == 409 and response.json()["detail"] == f"{DAY1} is already running."
    # Uploads wait for the run to finish.
    assert upload(analyst, {"positions": day_files[0]["positions"]}).status_code == 409
    work(factory)
    assert db_session.query(Job).count() == 1


def test_rerun_refused_after_sign_off(make_client, users, fund, day_files, factory, db_session):
    analyst = make_client("analyst1")
    upload_and_run(analyst, factory, day_files[0])
    sign_off(db_session, fund, DAY1)
    response = start_run(analyst)
    assert response.status_code == 409 and "signed off" in response.json()["detail"]

    # The next day cannot be run before the previous one is signed off, nor out of order.
    upload_and_run(analyst, factory, day_files[1], as_of=DAY2)
    assert start_run(analyst, DAY1).status_code == 409


# --------------------------------------------------------------------------- re-runs


def _decide(db_session, fund, case_id: str, user: User, decision: str, category: str, note: str = "",
            final_category: str | None = None) -> int:
    """Record a decision as the decisions API will (that API is built separately)."""
    day = db_session.execute(select(BusinessDay).where(BusinessDay.as_of == DAY1)).scalar_one()
    row = Decision(fund_id=fund.id, case_id=case_id, business_day_id=day.id, user_id=user.id, role=user.role,
                   decision=decision, category=category, final_category=final_category, note=note,
                   case_version=1)
    db_session.add(row)
    db_session.commit()
    return row.id


def test_rerun_reapplies_matching_decisions_and_voids_others(make_client, users, fund, day_files, factory,
                                                             db_session):
    analyst = make_client("analyst1")
    upload_and_run(analyst, factory, day_files[0])
    analyst1, approver1 = users["analyst1"], users["approver1"]
    keep = _decide(db_session, fund, TIMING_CASE, analyst1, "approve", "TIMING", "settles tomorrow")
    stale = _decide(db_session, fund, "EX-20261109-002", approver1, "reclassify", "PRICE_MISMATCH",
                    "was a price issue", final_category="PRICE_MISMATCH")  # the case is a STOCK_SPLIT now
    gone = _decide(db_session, fund, DIVIDEND_CASE, analyst1, "approve", "DIVIDEND")

    # The custodian re-sends its cash statement without the dividend line: that case disappears.
    fixed_cash = without_line(day_files[0]["cash"], DIVIDEND_SECURITY)
    assert upload(analyst, {"cash": fixed_cash}).json()["status"] == "validated"
    before = len(actions(db_session))
    assert start_run(analyst).status_code == 202
    work(factory)

    db_session.expire_all()
    timing = db_session.get(CaseRow, (fund.id, TIMING_CASE))
    assert (timing.status, timing.final_category, timing.version) == ("APPROVED", "TIMING", 2)
    assert timing.data["reviewed_by"] == "analyst1" and timing.data["review_note"] == "settles tomorrow"
    snap = db_session.get(CaseSnapshot, (fund.id, TIMING_CASE, DAY1))
    assert snap.status == "APPROVED"

    split = db_session.get(CaseRow, (fund.id, "EX-20261109-002"))
    assert split.status == "PENDING"
    assert db_session.get(CaseRow, (fund.id, DIVIDEND_CASE)) is None
    assert db_session.get(CaseSnapshot, (fund.id, DIVIDEND_CASE, DAY1)) is None

    decisions = {d.id: d for d in db_session.execute(select(Decision)).scalars()}
    assert decisions[keep].voided_at is None
    assert decisions[stale].voided_at is not None
    assert decisions[stale].void_reason == "the suggested cause changed from PRICE_MISMATCH to STOCK_SPLIT"
    assert decisions[gone].void_reason == "the case is no longer open after the re-run"

    entries = DbAuditLog(db_session).entries()[before:]
    assert [e["action"] for e in entries] == [
        "RUN_STARTED", "CASES_RAISED", "CASE_WITHDRAWN_BY_RERUN", "CASE_APPROVED",
        "DECISION_VOIDED_BY_RERUN", "DECISION_VOIDED_BY_RERUN", "RUN_FINISHED",
    ]
    approved = entries[3]
    assert approved["actor"] == "analyst1" and approved["payload"]["case_id"] == TIMING_CASE
    assert entries[2]["payload"]["case_id"] == DIVIDEND_CASE
    assert {e["payload"]["decision_id"] for e in entries[4:6]} == {stale, gone}
    assert entries[-1]["payload"]["rerun"] == {
        "decisions_reapplied": [keep], "decisions_voided": [stale, gone], "cases_withdrawn": [DIVIDEND_CASE],
    }
    assert verify_chain(db_session) == (True, None)


def test_rerun_of_unchanged_files_gives_the_same_cases(make_client, users, fund, day_files, factory, db_session):
    analyst = make_client("analyst1")
    upload_and_run(analyst, factory, day_files[0])
    first = {c.case_id: (c.category, c.nav_impact) for c in db_session.execute(select(CaseRow)).scalars()}
    assert start_run(analyst).status_code == 202
    work(factory)
    db_session.expire_all()
    rows = db_session.execute(select(CaseRow)).scalars().all()
    assert {c.case_id: (c.category, c.nav_impact) for c in rows} == first
    assert {c.version for c in rows} == {2}
    assert db_session.query(CaseSnapshot).count() == 4
    assert "CASE_WITHDRAWN_BY_RERUN" not in actions(db_session)


# --------------------------------------------------------------------------- AI switch and cache


def test_ai_off_by_default_makes_no_calls(make_client, users, fund, day_files, factory, db_session, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    asked = []
    monkeypatch.setattr(runner, "make_client", lambda *a, **k: asked.append(a) or FakeClient())
    upload_and_run(make_client("analyst1"), factory, day_files[0])
    assert asked == []
    assert not [a for a in actions(db_session) if a.startswith("AI_")]
    assert db_session.query(AICacheEntry).count() == 0


def test_ai_on_uses_and_fills_the_database_cache(make_client, users, make_fund, day_files, factory, db_session,
                                                 monkeypatch):
    fund = make_fund(settings={"ai_enabled": True})
    client = FakeClient()
    monkeypatch.setattr(runner, "make_client", lambda *a, **k: client)
    analyst = make_client("analyst1")
    upload_and_run(analyst, factory, day_files[0])
    assert client.calls == 4
    assert db_session.query(AICacheEntry).count() == 4
    calls = [e["payload"] for e in DbAuditLog(db_session).entries() if e["action"] == "AI_CALL"]
    assert len(calls) == 4 and not any(c["cached"] for c in calls) and not any(c["fallback_used"] for c in calls)
    case = db_session.get(CaseRow, (fund.id, TIMING_CASE))
    assert case.ai_category == "TIMING" and case.data["ai_status"] == "ACCEPTED"

    # A re-run asks the same questions and is answered from the cache.
    assert start_run(analyst).status_code == 202
    work(factory)
    assert client.calls == 4
    calls = [e["payload"] for e in DbAuditLog(db_session).entries() if e["action"] == "AI_CALL"]
    assert len(calls) == 8 and all(c["cached"] for c in calls[4:])
    summary = analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").json()["summary"]
    assert summary["ai"] == {"enabled": True, "available": True, "provider": "fake", "model": "fake-1",
                             "disagreements": 0}


def test_ai_on_without_a_key_falls_back_to_the_rules(make_client, users, make_fund, day_files, factory,
                                                     db_session, monkeypatch):
    make_fund(settings={"ai_enabled": True})
    monkeypatch.setattr(runner, "make_client", lambda *a, **k: None)
    upload_and_run(make_client("analyst1"), factory, day_files[0])
    assert "AI_UNAVAILABLE" in actions(db_session) and "AI_CALL" not in actions(db_session)
    assert db_session.query(CaseRow).count() == 4
