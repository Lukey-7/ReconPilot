"""The case queue, a case's detail and evidence, and decisions with stale-version protection."""

from __future__ import annotations

import threading
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from reconpilot_web import jobs
from reconpilot_web.auditlog import DbAuditLog, verify_chain
from reconpilot_web.models import BusinessDay, CaseRow, CaseSnapshot, Decision

from .conftest import FUND_CODE, FUND_START
from .test_upload import upload

DAY1, DAY2 = FUND_START, date(2026, 11, 10)
QUEUE = f"/api/funds/{FUND_CODE}/days/{DAY1}/cases"


@pytest.fixture
def factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


def run_day(client, factory, files, as_of: date = DAY1) -> None:
    assert upload(client, files, as_of=as_of).json()["status"] == "validated"
    response = client.post(f"/api/funds/{FUND_CODE}/days/{as_of}/run")
    assert response.status_code == 202, response.text
    assert jobs.work_one(factory, "test-worker") == response.json()["job_id"]


@pytest.fixture
def ran(make_client, users, fund, day_files, factory):
    """Day 1 uploaded and run by ``analyst1``; returns the analyst's client."""
    analyst = make_client("analyst1")
    run_day(analyst, factory, day_files[0])
    return analyst


def decide(client, case_id: str, decision: str = "approve", version: int = 1, **body):
    return client.post(f"/api/funds/{FUND_CODE}/cases/{case_id}/decision",
                       json={"decision": decision, "version": version, **body})


def actions(db_session) -> list[str]:
    db_session.expire_all()
    return [e["action"] for e in DbAuditLog(db_session).entries()]


# --------------------------------------------------------------------------- the queue


def test_queue_sorted_by_absolute_impact(ran, make_client, db_session, fund):
    response = ran.get(QUEUE)
    assert response.status_code == 200, response.text
    queue = response.json()
    assert len(queue) == 4
    assert [abs(c["nav_impact"]) for c in queue] == sorted((abs(c["nav_impact"]) for c in queue), reverse=True)
    assert set(queue[0]) == {
        "case_id", "security_id", "security_name", "category", "ai_category", "ai_flag", "status",
        "final_category", "nav_impact", "nav_impact_bp", "gross_exposure", "material", "escalated",
        "sla_breached", "age_days", "age_bucket", "version",
    }
    rows = {r.case_id: r for r in db_session.execute(select(CaseRow)).scalars()}
    for item in queue:
        row = rows[item["case_id"]]
        assert (item["category"], item["nav_impact"], item["material"], item["version"], item["status"]) == (
            row.category, row.nav_impact, row.material, row.version, "PENDING")
        assert item["security_name"]  # from the day's securities file
    # Every signed-in role can read it; nobody signed out can.
    assert make_client("viewer1").get(QUEUE).status_code == 200
    assert make_client().get(QUEUE).status_code == 401


def test_queue_needs_a_finished_run(make_client, users, fund, day_files):
    analyst = make_client("analyst1")
    assert analyst.get(QUEUE).status_code == 404
    upload(analyst, day_files[0])
    response = analyst.get(QUEUE)
    assert response.status_code == 409 and "not been run" in response.json()["detail"]


def test_filters(ran):
    queue = ran.get(QUEUE).json()

    def ids(**params):
        response = ran.get(QUEUE, params=params)
        assert response.status_code == 200, response.text
        return [c["case_id"] for c in response.json()]

    assert ids(material="true") == [c["case_id"] for c in queue if c["material"]]
    assert ids(material="false") == [c["case_id"] for c in queue if not c["material"]]
    assert ids(escalated="true") == [c["case_id"] for c in queue if c["escalated"]]
    assert ids(sla="true") == [c["case_id"] for c in queue if c["sla_breached"]]
    assert ids(status="pending") == [c["case_id"] for c in queue]
    assert ids(status="APPROVED") == []
    assert ids(age="0-1") == [c["case_id"] for c in queue]
    assert ids(age=">5") == []
    assert ids(ai_disagrees="true") == []
    first = queue[0]
    assert ids(category=first["category"]) == [c["case_id"] for c in queue if c["category"] == first["category"]]
    assert ids(q=first["security_id"].lower()) == [first["case_id"]]
    assert ids(q=first["security_name"][:6].upper()) == [
        c["case_id"] for c in queue if first["security_name"][:6].lower() in c["security_name"].lower()
    ]
    assert ids(q=first["case_id"]) == [first["case_id"]]

    # A reclassified case is found under its new cause as well as its suggested one.
    target = queue[-1]
    new_cause = "UNKNOWN" if target["category"] != "UNKNOWN" else "TIMING"
    assert decide(ran, target["case_id"], "reclassify", category=new_cause).status_code == 200
    assert target["case_id"] in ids(category=new_cause)
    assert ids(status="RECLASSIFIED") == [target["case_id"]]

    for bad in ({"status": "LOST"}, {"category": "GREMLINS"}, {"age": "6-9"}, {"material": "maybe"}):
        assert ran.get(QUEUE, params=bad).status_code == 422


# --------------------------------------------------------------------------- detail


def test_detail_has_evidence_and_history(ran, db_session, fund):
    case = ran.get(QUEUE).json()[0]
    url = f"/api/funds/{FUND_CODE}/cases/{case['case_id']}"
    detail = ran.get(url).json()
    assert detail["case_id"] == case["case_id"] and detail["as_of"] == str(DAY1)
    assert detail["version"] == 1 and detail["is_open"] is True and detail["day_status"] == "ready"
    assert detail["case"]["explanation"] and detail["case"]["break_ids"]
    assert {b["break_id"] for b in detail["breaks"]} == set(detail["case"]["break_ids"])
    assert detail["security"]["security_id"] == case["security_id"]
    assert detail["book_position"] is not None or detail["custodian_holding"] is not None
    for trade in detail["book_trades"]:
        assert trade["security_id"] == case["security_id"] or trade["trade_id"] in {
            b["reference"] for b in detail["breaks"]}
    assert all(line["security_id"] == case["security_id"] or line["reference"]
               for line in detail["custodian_cash"])
    assert [h["action"] for h in detail["history"] if h["type"] == "audit"] == [
        a for a in (e["action"] for e in DbAuditLog(db_session).entries()
                    if e["payload"].get("case_id") == case["case_id"])
    ]

    assert decide(ran, case["case_id"], "approve", note="agreed with custodian").status_code == 200
    history = ran.get(url).json()["history"]
    assert [(h["type"], h.get("action") or h.get("decision")) for h in history][-2:] == [
        ("audit", "CASE_APPROVED"), ("decision", "approve")]
    assert history[-1]["user"] == "analyst1" and history[-1]["note"] == "agreed with custodian"
    assert history[-1]["case_version"] == 1

    assert ran.get(f"/api/funds/{FUND_CODE}/cases/EX-NOPE").status_code == 404
    assert ran.get(url, params={"as_of": str(DAY2)}).status_code == 404
    assert ran.get(url, params={"as_of": "13/11/2026"}).status_code == 422


# --------------------------------------------------------------------------- deciding


def test_decision_updates_case_snapshot_and_audit(ran, db_session, fund):
    case = ran.get(QUEUE).json()[-1]
    response = decide(ran, case["case_id"], "reclassify", category="unknown", note="not what the rules say")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["final_category"], body["version"]) == ("RECLASSIFIED", "UNKNOWN", 2)
    assert body["case"]["reviewed_by"] == "analyst1" and body["case"]["reviewed_role"] == "analyst"

    db_session.expire_all()
    row = db_session.get(CaseRow, (fund.id, case["case_id"]))
    assert (row.status, row.final_category, row.version) == ("RECLASSIFIED", "UNKNOWN", 2)
    snap = db_session.get(CaseSnapshot, (fund.id, case["case_id"], DAY1))
    assert snap.status == "RECLASSIFIED" and snap.data["final_category"] == "UNKNOWN"
    decision = db_session.execute(select(Decision)).scalar_one()
    assert (decision.decision, decision.category, decision.final_category, decision.case_version, decision.role) == (
        "reclassify", case["category"], "UNKNOWN", 1, "analyst")
    entry = DbAuditLog(db_session).entries()[-1]
    assert entry["action"] == "CASE_RECLASSIFIED" and entry["actor"] == "analyst1"
    assert entry["payload"]["case_id"] == case["case_id"] and entry["payload"]["final"] == "UNKNOWN"
    assert verify_chain(db_session) == (True, None)

    # Deciding again needs the new version.
    assert decide(ran, case["case_id"], "approve", version=2).json()["status"] == "APPROVED"


def test_viewer_cannot_decide(ran, make_client, db_session):
    case_id = ran.get(QUEUE).json()[0]["case_id"]
    viewer = make_client("viewer1")
    assert decide(viewer, case_id).status_code == 403
    signed_out = make_client()
    assert decide(signed_out, case_id).status_code in (401, 403)
    assert db_session.query(Decision).count() == 0


def test_reject_needs_note(ran, db_session):
    case_id = ran.get(QUEUE).json()[0]["case_id"]
    response = decide(ran, case_id, "reject")
    assert response.status_code == 422 and "note" in response.json()["detail"]
    assert decide(ran, case_id, "reject", note="   ").status_code == 422
    assert decide(ran, case_id, "reclassify").status_code == 422
    assert decide(ran, case_id, "reclassify", category="GREMLINS").status_code == 422
    assert decide(ran, case_id, "shrug").status_code == 422
    assert db_session.query(Decision).count() == 0
    response = decide(ran, case_id, "reject", note="custodian is right")
    assert response.status_code == 200 and response.json()["status"] == "REJECTED"


def test_stale_version_409(ran, make_client, db_session, fund):
    """Review focus 1: two people load version 1; the second decision is refused and the first stands."""
    other = make_client("approver1")
    case_id = ran.get(QUEUE).json()[0]["case_id"]
    assert other.get(QUEUE).json()[0]["version"] == 1

    assert decide(ran, case_id, "approve", note="first").status_code == 200
    response = decide(other, case_id, "reject", note="second")
    assert response.status_code == 409 and "reload" in response.json()["detail"]

    db_session.expire_all()
    row = db_session.get(CaseRow, (fund.id, case_id))
    assert (row.status, row.version, row.data["review_note"]) == ("APPROVED", 2, "first")
    assert db_session.query(Decision).count() == 1
    assert actions(db_session).count("CASE_APPROVED") == 1 and "CASE_REJECTED" not in actions(db_session)


def test_simultaneous_decisions_one_wins(ran, make_client, db_session, fund):
    """Review focus 1 under real concurrency: two requests at once, exactly one succeeds."""
    case_id = ran.get(QUEUE).json()[0]["case_id"]
    clients = [ran, make_client("approver1")]
    barrier = threading.Barrier(2)
    results: list[int] = []

    def go(client, decision, note):
        barrier.wait()
        results.append(decide(client, case_id, decision, note=note).status_code)

    threads = [threading.Thread(target=go, args=(clients[0], "approve", "a")),
               threading.Thread(target=go, args=(clients[1], "reject", "b"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409]
    db_session.expire_all()
    assert db_session.get(CaseRow, (fund.id, case_id)).version == 2
    assert db_session.query(Decision).count() == 1
    assert verify_chain(db_session) == (True, None)


def test_decision_after_sign_off_409(ran, db_session, fund):
    case_id = ran.get(QUEUE).json()[0]["case_id"]
    day = db_session.execute(select(BusinessDay).where(BusinessDay.as_of == DAY1)).scalar_one()
    day.status = "signed_off"
    db_session.commit()
    response = decide(ran, case_id)
    assert response.status_code == 409 and "signed off" in response.json()["detail"]
    assert db_session.query(Decision).count() == 0


def test_decision_refused_while_running(ran, factory, db_session):
    case_id = ran.get(QUEUE).json()[0]["case_id"]
    assert ran.post(f"/api/funds/{FUND_CODE}/days/{DAY1}/run").status_code == 202
    response = decide(ran, case_id)
    assert response.status_code == 409 and "running" in response.json()["detail"]
    jobs.work_one(factory, "test-worker")
    assert decide(ran, case_id, version=2).status_code == 200  # the re-run bumped the version


def test_cleared_case_cannot_be_decided(ran, make_client, factory, day_files, db_session, fund):
    db_session.expire_all()
    day = db_session.execute(select(BusinessDay).where(BusinessDay.as_of == DAY1)).scalar_one()
    day.status = "signed_off"
    db_session.commit()
    run_day(ran, factory, day_files[1], as_of=DAY2)
    db_session.expire_all()
    cleared = db_session.execute(select(CaseRow).where(CaseRow.cleared_on.is_not(None))).scalars().all()
    assert cleared, "the generated day 2 clears at least one case"
    response = decide(ran, cleared[0].case_id, version=cleared[0].version)
    assert response.status_code == 409 and "cleared" in response.json()["detail"]
    # The cleared case is no longer in day 2's queue but still in day 1's.
    day2 = ran.get(f"/api/funds/{FUND_CODE}/days/{DAY2}/cases").json()
    assert cleared[0].case_id not in {c["case_id"] for c in day2}
    assert cleared[0].case_id in {c["case_id"] for c in ran.get(QUEUE).json()}
    detail = ran.get(f"/api/funds/{FUND_CODE}/cases/{cleared[0].case_id}").json()
    assert detail["as_of"] == str(DAY2) and detail["is_open"] is False


def test_decision_carries_to_the_next_day(ran, factory, day_files, db_session, fund):
    """A decision updates the day's ledger, which is what the next day's run carries forward."""
    queue = ran.get(QUEUE).json()
    for case in queue:
        assert decide(ran, case["case_id"], "approve").status_code == 200
    day = db_session.execute(select(BusinessDay).where(BusinessDay.as_of == DAY1)).scalar_one()
    day.status = "signed_off"
    db_session.commit()
    run_day(ran, factory, day_files[1], as_of=DAY2)
    day2 = {c["case_id"]: c for c in ran.get(f"/api/funds/{FUND_CODE}/days/{DAY2}/cases").json()}
    carried = [c for c in queue if c["case_id"] in day2]
    assert carried
    for case in carried:
        if day2[case["case_id"]]["category"] == case["category"]:
            assert day2[case["case_id"]]["status"] == "APPROVED"
