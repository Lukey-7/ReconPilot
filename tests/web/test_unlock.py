"""Unlocking a signed-off day: an administrator asks, a different approver confirms within 24 hours."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from reconpilot_web.models import AuditEntry, BusinessDay, UnlockRequest

from .conftest import FUND_CODE, FUND_START
from .test_release import decide, decide_all, queue, run_day
from .test_upload import upload

DAY1, DAY2 = FUND_START, date(2026, 11, 10)
UNLOCK = f"/api/funds/{FUND_CODE}/days/{DAY1}/unlock"
REASON = "The custodian restated a price for 9 November after release."


@pytest.fixture
def factory(db_engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def signed_off(make_user, users, make_client, fund, day_files, factory):
    """Day 1 run, decided and signed off by ``approver2``; clients for everyone, ``admin1`` an approver-admin."""
    make_user("admin1", "approver", is_admin=True)
    make_user("admin2", "analyst", is_admin=True)
    clients = {name: make_client(name) for name in
               ("analyst1", "approver1", "approver2", "viewer1", "admin1", "admin2")}
    run_day(clients["analyst1"], factory, day_files[0])
    decide_all(clients["analyst1"], clients["approver1"])
    response = clients["approver2"].post(f"/api/funds/{FUND_CODE}/days/{DAY1}/signoff")
    assert response.status_code == 200, response.text
    return clients


def actions(db_session) -> list[str]:
    db_session.expire_all()
    return list(db_session.execute(select(AuditEntry.action).order_by(AuditEntry.seq)).scalars())


def payloads(db_session, action: str) -> list[dict]:
    db_session.expire_all()
    return list(db_session.execute(
        select(AuditEntry.payload).where(AuditEntry.action == action).order_by(AuditEntry.seq)).scalars())


def ask(client, reason: str = REASON):
    return client.post(UNLOCK, json={"reason": reason})


def day_row(db_session, as_of: date = DAY1) -> BusinessDay:
    db_session.expire_all()
    return db_session.execute(select(BusinessDay).where(BusinessDay.as_of == as_of)).scalar_one()


# --------------------------------------------------------------------------- the whole journey


def test_admin_asks_another_approver_confirms_and_the_day_is_signed_off_again(signed_off, db_session):
    c = signed_off
    state = c["viewer1"].get(UNLOCK).json()
    assert state["unlockable"] and state["pending"] is None and not state["requestable_by_me"]
    assert c["admin1"].get(UNLOCK).json()["requestable_by_me"] is True

    asked = ask(c["admin1"])
    assert asked.status_code == 201, asked.text
    pending = asked.json()["pending"]
    assert pending["status"] == "pending" and pending["reason"] == REASON and pending["requested_by"] == "admin1"
    assert pending["withdrawable_by_me"] and not pending["confirmable_by_me"]
    expires = datetime.fromisoformat(pending["expires_at"]) - datetime.fromisoformat(pending["requested_at"])
    assert expires == timedelta(hours=24)
    seen_by_approver = c["approver1"].get(UNLOCK).json()["pending"]
    assert seen_by_approver["confirmable_by_me"] and seen_by_approver["declinable_by_me"]
    assert not c["analyst1"].get(UNLOCK).json()["pending"]["confirmable_by_me"]
    assert day_row(db_session).status == "signed_off"  # nothing changes until it is confirmed

    confirm = f"{UNLOCK}/{pending['id']}/confirm"
    own = c["admin1"].post(confirm, json={})
    assert own.status_code == 403 and "different approver" in own.json()["detail"]
    assert c["analyst1"].post(confirm, json={}).status_code == 403
    assert c["viewer1"].post(confirm, json={}).status_code == 403
    assert c["admin2"].post(confirm, json={}).status_code == 403  # an administrator, but an analyst

    done = c["approver1"].post(confirm, json={"note": "Agreed: price restated by the custodian."})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["day_status"] == "ready" and body["signed_off_by"] is None and body["pending"] is None
    assert body["history"][0]["status"] == "confirmed" and body["history"][0]["decided_by"] == "approver1"
    row = day_row(db_session)
    assert row.status == "ready" and row.signed_off_by is None and row.signed_off_at is None

    (entry,) = payloads(db_session, "DAY_UNLOCKED")
    assert entry["as_of"] == str(DAY1) and entry["reason"] == REASON and entry["requested_by"] == "admin1"
    assert entry["previously_signed_off_by"] == "approver2" and entry["note"].startswith("Agreed")
    assert entry["next_day"] == str(DAY2)
    assert actions(db_session)[-2:] == ["UNLOCK_REQUESTED", "DAY_UNLOCKED"]

    # The day is open again: the release status says so, a case can be decided again ...
    release = c["approver2"].get(f"/api/funds/{FUND_CODE}/days/{DAY1}/release").json()
    assert release["signed_off"] is False and release["ready"] is True
    case = queue(c["analyst1"])[0]
    decide(c["approver1"] if case["escalated"] else c["analyst1"], case, "approve",
           note="Re-checked against the restated price.")
    # ... the next day cannot be loaded until it is signed off again ...
    nxt = c["analyst1"].get(f"/api/funds/{FUND_CODE}/days")
    assert nxt.json()["next_day"] is None
    # ... and it must be signed off again, four-eyes and all.
    again = c["approver2"].post(f"/api/funds/{FUND_CODE}/days/{DAY1}/signoff")
    assert again.status_code == 200, again.text
    assert day_row(db_session).status == "signed_off"
    assert actions(db_session).count("DAY_SIGNED_OFF") == 2
    assert c["approver1"].post("/api/audit/verify").json()["chain_ok"] is True


# --------------------------------------------------------------------------- who and when


def test_only_an_administrator_may_ask_and_with_a_reason(signed_off):
    c = signed_off
    for name in ("analyst1", "approver1", "viewer1"):
        assert ask(c[name]).status_code == 403
    short = ask(c["admin1"], "oops")
    assert short.status_code == 422
    assert ask(c["admin2"]).status_code == 201  # an analyst with the admin flag may ask


def test_one_pending_request_per_day(signed_off):
    assert ask(signed_off["admin1"]).status_code == 201
    second = ask(signed_off["admin2"])
    assert second.status_code == 409 and "already waiting" in second.json()["detail"]


def test_a_day_not_signed_off_cannot_be_unlocked(make_user, users, make_client, fund, day_files, factory):
    make_user("admin1", "approver", is_admin=True)
    admin = make_client("admin1")
    run_day(make_client("analyst1"), factory, day_files[0])
    refused = ask(admin)
    assert refused.status_code == 409 and "not signed off" in refused.json()["detail"]
    assert admin.get(UNLOCK).json()["unlockable"] is False
    assert admin.get(f"/api/funds/{FUND_CODE}/days/2026-11-11/unlock").status_code == 404


def test_not_once_the_next_day_has_run(signed_off, day_files, factory, db_session):
    c = signed_off
    # Loaded but not run: still allowed.
    assert upload(c["analyst1"], day_files[1], as_of=DAY2).json()["status"] == "validated"
    assert c["admin1"].get(UNLOCK).json()["unlockable"] is True
    pending = ask(c["admin1"]).json()["pending"]

    # The next day runs before anyone confirms: the confirmation is refused.
    response = c["analyst1"].post(f"/api/funds/{FUND_CODE}/days/{DAY2}/run")
    assert response.status_code == 202
    from reconpilot_web import jobs

    jobs.work_one(factory, "test-worker")
    refused = c["approver1"].post(f"{UNLOCK}/{pending['id']}/confirm", json={})
    assert refused.status_code == 409 and "already been run" in refused.json()["detail"]
    assert day_row(db_session).status == "signed_off"
    state = c["admin1"].get(UNLOCK).json()
    assert state["unlockable"] is False and "already been run" in state["problem"]
    assert ask(c["admin2"]).status_code == 409


def test_unlocked_with_the_next_day_loaded_the_day_is_run_again_and_the_fund_goes_on(
        signed_off, day_files, factory, db_session):
    """The next day's files were loaded (not run) before the unlock: the unlocked day can take
    corrected files, be run, decided and signed off again, and then the next day runs."""
    c = signed_off
    assert upload(c["analyst1"], day_files[1], as_of=DAY2).json()["status"] == "validated"
    pending = ask(c["admin1"]).json()["pending"]
    assert c["approver1"].post(f"{UNLOCK}/{pending['id']}/confirm", json={}).status_code == 200

    # The next day waits for the new sign-off.
    waiting = c["analyst1"].post(f"/api/funds/{FUND_CODE}/days/{DAY2}/run")
    assert waiting.status_code == 409 and f"Sign off {DAY1} first" in waiting.json()["detail"]

    # Corrected files for the unlocked day, run again, decided and signed off again.
    run_day(c["analyst1"], factory, day_files[0])
    decide_all(c["analyst1"], c["approver1"])
    signoff = c["approver2"].post(f"/api/funds/{FUND_CODE}/days/{DAY1}/signoff")
    assert signoff.status_code == 200, signoff.text
    assert day_row(db_session).status == "signed_off"

    # And the fund moves on: the next day runs from the new sign-off.
    response = c["analyst1"].post(f"/api/funds/{FUND_CODE}/days/{DAY2}/run")
    assert response.status_code == 202, response.text
    from reconpilot_web import jobs

    jobs.work_one(factory, "test-worker")
    assert day_row(db_session, DAY2).status == "ready"


def test_an_unlocked_day_cannot_run_again_once_a_later_day_has_run(signed_off, day_files, factory, db_session):
    """Guard on the run itself: a later day that has been run blocks a run of an earlier day."""
    c = signed_off
    run_day(c["analyst1"], factory, day_files[1], as_of=DAY2)
    # Force the inconsistent state directly; the API does not allow unlocking here.
    db_session.execute(update(BusinessDay).where(BusinessDay.as_of == DAY1).values(status="ready"))
    db_session.commit()
    refused = c["analyst1"].post(f"/api/funds/{FUND_CODE}/days/{DAY1}/run")
    assert refused.status_code == 409 and f"{DAY2} has already been run" in refused.json()["detail"]


def test_only_the_latest_signed_off_day(signed_off, day_files, factory):
    c = signed_off
    run_day(c["analyst1"], factory, day_files[1], as_of=DAY2)
    for case in queue(c["analyst1"], DAY2):
        decide(c["approver1"] if case["escalated"] else c["analyst1"], case)
    assert c["approver2"].post(f"/api/funds/{FUND_CODE}/days/{DAY2}/signoff").status_code == 200
    refused = ask(c["admin1"])
    assert refused.status_code == 409 and "latest signed-off day" in refused.json()["detail"]
    later = c["admin1"].post(f"/api/funds/{FUND_CODE}/days/{DAY2}/unlock", json={"reason": REASON})
    assert later.status_code == 201


# --------------------------------------------------------------------------- declining, withdrawing, expiry


def test_decline_needs_a_note_and_withdraw_does_not(signed_off, db_session):
    c = signed_off
    first = ask(c["admin1"]).json()["pending"]
    decline = f"{UNLOCK}/{first['id']}/decline"
    assert c["analyst1"].post(decline, json={"note": "no"}).status_code == 403
    assert c["approver1"].post(decline, json={}).status_code == 422
    declined = c["approver1"].post(decline, json={"note": "Correct it on today's run instead."})
    assert declined.status_code == 200 and declined.json()["history"][0]["status"] == "declined"
    assert c["approver1"].post(f"{UNLOCK}/{first['id']}/confirm", json={}).status_code == 409

    second = ask(c["admin1"]).json()["pending"]
    withdrawn = c["admin1"].post(f"{UNLOCK}/{second['id']}/decline", json={})
    assert withdrawn.status_code == 200
    assert [r["status"] for r in withdrawn.json()["history"]] == ["withdrawn", "declined"]
    assert payloads(db_session, "UNLOCK_DECLINED")[0]["note"] == "Correct it on today's run instead."
    assert len(payloads(db_session, "UNLOCK_WITHDRAWN")) == 1
    assert day_row(db_session).status == "signed_off"


def test_a_request_expires_after_24_hours(signed_off, db_session, db_engine):
    c = signed_off
    pending = ask(c["admin1"]).json()["pending"]
    with db_engine.begin() as conn:
        conn.execute(update(UnlockRequest).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    assert c["approver1"].get(UNLOCK).json()["history"][0]["status"] == "expired"
    late = c["approver1"].post(f"{UNLOCK}/{pending['id']}/confirm", json={})
    assert late.status_code == 409 and "expired" in late.json()["detail"]
    assert day_row(db_session).status == "signed_off"
    (entry,) = payloads(db_session, "UNLOCK_EXPIRED")
    assert entry["request_id"] == pending["id"] and entry["requested_by"] == "admin1"
    assert ask(c["admin1"]).status_code == 201  # a fresh request can be made


def test_unknown_request_is_404(signed_off):
    assert signed_off["approver1"].post(f"{UNLOCK}/999/confirm", json={}).status_code == 404
