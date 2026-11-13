"""One release status on the server, sign-off with four-eyes, and day locking."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from reconpilot.models import Case, Category
from reconpilot_web import jobs
from reconpilot_web.auditlog import DbAuditLog, verify_chain
from reconpilot_web.models import BusinessDay, User
from reconpilot_web.release import (
    CHECK_FAILED,
    ESCALATED_NEEDS_APPROVER,
    FOUR_EYES,
    MATERIAL_NOT_APPROVED,
    NOT_RUN,
    PENDING_DECISIONS,
    can_sign_off,
    compute_release,
)

from .conftest import FUND_CODE, FUND_START
from .test_upload import upload

DAY1, DAY2 = FUND_START, date(2026, 11, 10)
DAY_URL = f"/api/funds/{FUND_CODE}/days/{DAY1}"


@pytest.fixture
def factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


def run_day(client, factory, files, as_of: date = DAY1) -> None:
    assert upload(client, files, as_of=as_of).json()["status"] == "validated"
    response = client.post(f"/api/funds/{FUND_CODE}/days/{as_of}/run")
    assert response.status_code == 202, response.text
    assert jobs.work_one(factory, "test-worker") == response.json()["job_id"]


# Day 1 of the generated files has a dividend case of about 0.66 bp of NAV: with the
# materiality threshold at 0.5 bp it is material, so escalated, from the start.
MATERIALITY_BP = 0.5


@pytest.fixture
def ran(make_client, users, make_fund, day_files, factory):
    """Day 1 uploaded and run by ``analyst1`` for a fund with a 0.5 bp threshold; the analyst's client."""
    make_fund(settings={"materiality_bp": MATERIALITY_BP})
    analyst = make_client("analyst1")
    run_day(analyst, factory, day_files[0])
    return analyst


def queue(client, as_of: date = DAY1) -> list[dict]:
    return client.get(f"/api/funds/{FUND_CODE}/days/{as_of}/cases").json()


def decide(client, case: dict, decision: str = "approve", **body):
    response = client.post(f"/api/funds/{FUND_CODE}/cases/{case['case_id']}/decision",
                           json={"decision": decision, "version": case["version"], **body})
    assert response.status_code == 200, response.text
    return response.json()


def release(client, as_of: date = DAY1) -> dict:
    response = client.get(f"/api/funds/{FUND_CODE}/days/{as_of}/release", params={"for_user": "me"})
    assert response.status_code == 200, response.text
    return response.json()


def codes(body: dict, key: str = "reasons") -> list[str]:
    return [r["code"] for r in body[key]]


def decide_all(analyst, approver) -> None:
    """The analyst decides ordinary cases; the approver decides escalated ones."""
    for case in queue(analyst):
        decide(approver if case["escalated"] else analyst, case)


def actions(db_session) -> list[str]:
    db_session.expire_all()
    return [e["action"] for e in DbAuditLog(db_session).entries()]


# --------------------------------------------------------------------------- the status


def test_ready_only_when_all_conditions_met(ran, make_client):
    approver1, approver2 = make_client("approver1"), make_client("approver2")
    cases = queue(ran)
    material = [c["case_id"] for c in cases if c["material"]]
    escalated = [c["case_id"] for c in cases if c["escalated"]]
    assert material and escalated, "the generated day has a material, escalated case"

    body = release(ran)
    assert body["ready"] is False and body["signed_off"] is False
    assert codes(body) == [PENDING_DECISIONS, MATERIAL_NOT_APPROVED, ESCALATED_NEEDS_APPROVER]
    reasons = {r["code"]: r for r in body["reasons"]}
    assert reasons[PENDING_DECISIONS]["case_ids"] == [c["case_id"] for c in cases]
    assert reasons[MATERIAL_NOT_APPROVED]["case_ids"] == material
    assert reasons[ESCALATED_NEEDS_APPROVER]["case_ids"] == escalated

    # The analyst decides everything: nothing is pending, but escalated cases still need an approver.
    for case in cases:
        decide(ran, case)
    body = release(ran)
    assert codes(body) == [ESCALATED_NEEDS_APPROVER] and body["ready"] is False

    # An approver confirms the escalated cases: the day is ready.
    for case in queue(ran):
        if case["escalated"]:
            decide(approver1, case)
    body = release(approver2)
    assert body["ready"] is True and body["reasons"] == []
    assert body["signable_by_me"] is True and body["blocking_for_me"] == []
    # The analyst cannot sign off, and approver1 decided cases today.
    assert release(ran)["signable_by_me"] is False
    mine = release(approver1)
    assert mine["ready"] is True and mine["signable_by_me"] is False
    assert codes(mine, "blocking_for_me") == [FOUR_EYES]
    assert mine["blocking_for_me"][0]["case_ids"] == escalated

    # The day's own record shows the same status.
    day = ran.get(DAY_URL).json()
    assert day["release"] == {"ready": True, "reasons": []}


def test_rejected_material_case_still_blocks(ran, make_client):
    approver1 = make_client("approver1")
    for case in queue(ran):
        if case["material"]:
            decide(approver1, case, "reject", note="the book is right")
        else:
            decide(ran, case)
    body = release(ran)
    assert codes(body) == [MATERIAL_NOT_APPROVED]


def test_engine_nav_release_check_renamed(ran, make_client):
    body = release(ran)
    names = [c["name"] for c in body["checks"]]
    assert "NAV release" not in names and names[-1] == "Material cases approved"
    assert body["checks"][-1]["status"] == "FAIL"  # material cases are waiting
    # It is not double-counted as a failed check.
    assert CHECK_FAILED not in codes(body)

    decide_all(ran, make_client("approver1"))
    body = release(ran)
    assert body["checks"][-1]["status"] == "PASS" and body["ready"] is True


def test_day_record_never_contradicts_release(ran, make_client):
    """The day's record shows the same status and checks as the release endpoint, before and after."""
    def same() -> dict:
        day, body = ran.get(DAY_URL).json(), release(ran)
        assert day["release"] == {"ready": body["ready"], "reasons": body["reasons"]}
        assert day["checks"] == body["checks"]
        assert "NAV release" not in [c["name"] for c in day["checks"]]
        return day

    day = same()
    assert day["release"]["ready"] is False and day["checks"][-1]["status"] == "FAIL"
    decide_all(ran, make_client("approver1"))
    day = same()
    assert day["release"]["ready"] is True and day["checks"][-1]["status"] == "PASS"


def test_not_run_and_failed_checks():
    day = BusinessDay(status="validated", run_at=None)
    assert [r.code for r in compute_release(day, [], []).reasons] == [NOT_RUN]
    assert [r.code for r in compute_release(None, [], []).reasons] == [NOT_RUN]
    failed = compute_release(BusinessDay(status="failed", run_at=None), [], []).reasons
    assert [(r.code, r.message) for r in failed] == [(NOT_RUN, "The day failed its last run.")]

    from datetime import datetime, timezone

    ran = BusinessDay(status="ready", run_at=datetime.now(timezone.utc))
    checks = [
        {"name": "Cash tie-out", "status": "FAIL", "detail": "gap 10.00"},
        {"name": "Stale prices", "status": "WARN", "detail": ""},
        {"name": "NAV release", "status": "FAIL", "detail": "material"},
    ]
    status = compute_release(ran, [], checks)
    assert status.ready is False
    assert [(r.code, r.message) for r in status.reasons] == [(CHECK_FAILED, "Cash tie-out failed: gap 10.00")]

    case = Case("EX-1", "SEC", Category.TIMING, 0.9, "", "", status="APPROVED", reviewed_by="ann",
                reviewed_role="approver")
    user = User(username="ann", role="approver")
    ready = compute_release(ran, [case], [])
    assert ready.ready is True
    assert [r.code for r in can_sign_off(ready, [case], user)] == [FOUR_EYES]
    other = User(username="tom", role="approver")
    assert can_sign_off(ready, [case], other) == []
    assert [r.code for r in can_sign_off(ready, [case], other, decided_case_ids={"EX-1"})] == [FOUR_EYES]


def test_release_status_identical_for_every_role(ran, make_client):
    clients = {name: make_client(name) for name in ("approver1", "approver2", "viewer1")} | {"analyst1": ran}
    bodies = {name: release(c) for name, c in clients.items()}
    shared = {name: {k: v for k, v in b.items() if k != "signable_by_me"} for name, b in bodies.items()}
    assert all(s == shared["analyst1"] for s in shared.values())
    assert not any(b["signable_by_me"] for b in bodies.values())  # blocked for everyone

    decide_all(ran, make_client("approver1"))
    bodies = {name: release(c) for name, c in clients.items()}
    common = {name: {k: v for k, v in b.items() if k not in ("signable_by_me", "blocking_for_me")}
              for name, b in bodies.items()}
    assert all(c == common["analyst1"] for c in common.values())
    assert {name: b["signable_by_me"] for name, b in bodies.items()} == {
        "analyst1": False, "approver1": False, "approver2": True, "viewer1": False}


# --------------------------------------------------------------------------- signing off


def test_analyst_cannot_sign_off(ran, make_client, db_session):
    decide_all(ran, make_client("approver1"))
    assert ran.post(f"{DAY_URL}/signoff").status_code == 403
    assert make_client("viewer1").post(f"{DAY_URL}/signoff").status_code == 403
    assert "DAY_SIGNED_OFF" not in actions(db_session)


def test_blocked_sign_off_is_refused_and_audited(ran, make_client, db_session):
    approver2 = make_client("approver2")
    response = approver2.post(f"{DAY_URL}/signoff")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert [r["code"] for r in detail["reasons"]] == [PENDING_DECISIONS, MATERIAL_NOT_APPROVED,
                                                     ESCALATED_NEEDS_APPROVER]
    entry = DbAuditLog(db_session).entries()[-1]
    assert entry["action"] == "SIGN_OFF_BLOCKED" and entry["actor"] == "approver2"
    assert ran.get(DAY_URL).json()["status"] == "ready"


def test_four_eyes_blocks_deciding_approver(ran, make_client, db_session):
    approver1 = make_client("approver1")
    decide_all(ran, approver1)
    response = approver1.post(f"{DAY_URL}/signoff")
    assert response.status_code == 409
    assert [r["code"] for r in response.json()["detail"]["reasons"]] == [FOUR_EYES]
    entry = DbAuditLog(db_session).entries()[-1]
    assert entry["action"] == "SIGN_OFF_BLOCKED" and entry["payload"]["reasons"][0]["code"] == FOUR_EYES
    assert ran.get(DAY_URL).json()["status"] == "ready"


def test_four_eyes_counts_a_decision_later_overridden(ran, make_client):
    """An approver who decided a case today cannot sign off, even if someone else decided it again."""
    approver1, approver2 = make_client("approver1"), make_client("approver2")
    escalated = [c for c in queue(ran) if c["escalated"]]
    for case in queue(ran):
        decide(approver1 if case["escalated"] else ran, case)
    first = next(c for c in queue(ran) if c["case_id"] == escalated[0]["case_id"])
    decide(approver2, first)  # approver2 decides it again, so the case shows approver2 now
    for case in queue(ran):
        if case["escalated"] and case["case_id"] != first["case_id"]:
            decide(approver2, case)
    blocking = release(approver1)["blocking_for_me"]
    assert [r["code"] for r in blocking] == [FOUR_EYES]
    assert approver1.post(f"{DAY_URL}/signoff").status_code == 409


def test_signoff_locks_day_and_unblocks_next_upload(ran, make_client, factory, day_files, db_session):
    approver1, approver2 = make_client("approver1"), make_client("approver2")
    # The next day cannot be loaded yet.
    assert upload(ran, day_files[1], as_of=DAY2).status_code == 409
    decide_all(ran, approver1)
    case = queue(ran)[0]

    response = approver2.post(f"{DAY_URL}/signoff")
    assert response.status_code == 200, response.text
    day = response.json()
    assert day["status"] == "signed_off" and day["signed_off_by"] == "approver2" and day["signed_off_at"]
    assert day["release"] == {"ready": True, "reasons": []}
    log = actions(db_session)
    assert log[-1] == "DAY_SIGNED_OFF"
    entry = DbAuditLog(db_session).entries()[-1]
    assert entry["actor"] == "approver2" and entry["payload"] == {"cases": len(queue(ran))}
    assert verify_chain(db_session) == (True, None)

    # Locked: no more decisions, files, runs or second sign-off.
    response = ran.post(f"/api/funds/{FUND_CODE}/cases/{case['case_id']}/decision",
                        json={"decision": "reject", "note": "late", "version": case["version"]})
    assert response.status_code == 409
    assert upload(ran, {"cash": day_files[0]["cash"]}).status_code == 409
    assert ran.post(f"{DAY_URL}/run").status_code == 409
    assert approver2.post(f"{DAY_URL}/signoff").status_code == 409
    body = release(approver2)
    assert body["signed_off"] is True and body["signable_by_me"] is False

    # The next business day can now be loaded and run.
    run_day(ran, factory, day_files[1], as_of=DAY2)
    assert release(ran, DAY2)["ready"] is False

    db_session.expire_all()
    row = db_session.execute(select(BusinessDay).where(BusinessDay.as_of == DAY1)).scalar_one()
    assert row.release_ready is True and row.signed_off_by is not None


def test_signoff_of_a_day_that_has_not_run(make_client, users, fund, day_files):
    approver = make_client("approver2")
    assert approver.post(f"{DAY_URL}/signoff").status_code == 404
    upload(make_client("analyst1"), day_files[0])
    response = approver.post(f"{DAY_URL}/signoff")
    assert response.status_code == 409
    assert [r["code"] for r in response.json()["detail"]["reasons"]] == [NOT_RUN]
    assert release(approver)["reasons"][0]["code"] == NOT_RUN
