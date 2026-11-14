"""A business day's audit trail, as the sign-off screen shows it."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from reconpilot_web.validation import FILE_KINDS

from .conftest import FUND_CODE
from .test_release import (
    DAY1,
    DAY2,
    DAY_URL,
    decide_all,
    factory,  # noqa: F401  (fixture)
    queue,
    ran,  # noqa: F401  (fixture)
    run_day,
)


def trail(client, as_of: date = DAY1, code: str = FUND_CODE) -> dict:
    response = client.get(f"/api/funds/{code}/days/{as_of}/audit")
    assert response.status_code == 200, response.text
    return response.json()


def actions(body: dict) -> list[str]:
    return [e["action"] for e in body["entries"]]


def test_trail_needs_sign_in_and_a_day(client, make_client, users, fund):
    assert client.get(f"{DAY_URL}/audit").status_code == 401
    viewer = make_client("viewer1")
    response = viewer.get(f"{DAY_URL}/audit")
    assert response.status_code == 404
    assert response.json()["detail"] == f"No files have been uploaded for {DAY1}."
    assert viewer.get(f"/api/funds/{FUND_CODE}/days/not-a-day/audit").status_code == 422
    assert viewer.get(f"/api/funds/NOPE/days/{DAY1}/audit").status_code == 404


def test_trail_of_a_worked_day(ran, make_client):  # noqa: F811
    approver1, approver2, viewer = make_client("approver1"), make_client("approver2"), make_client("viewer1")
    assert approver2.post(f"{DAY_URL}/signoff").status_code == 409  # refused: cases pending
    decide_all(ran, approver1)
    assert approver2.post(f"{DAY_URL}/signoff").status_code == 200

    body = trail(viewer)  # any signed-in role may read it
    assert body["fund"] == FUND_CODE and body["as_of"] == str(DAY1)
    assert body["chain_ok"] is True and body["broken_at"] is None
    got = actions(body)
    assert got[:2] == ["FILES_UPLOADED", "VALIDATION_PASSED"]
    assert got.index("RUN_STARTED") < got.index("CASES_RAISED") < got.index("RUN_FINISHED")
    assert got[-1] == "DAY_SIGNED_OFF"
    assert "SIGN_OFF_BLOCKED" in got
    # Sign-ins and the fund's creation are not part of the day.
    assert not {"SIGN_IN", "FUND_CREATED"} & set(got)

    seqs = [e["seq"] for e in body["entries"]]
    assert seqs == sorted(seqs)
    entry = body["entries"][-1]
    assert set(entry) == {"seq", "ts", "actor", "role", "action", "case_id", "payload", "prev_hash", "hash"}
    assert entry["actor"] == "approver2" and entry["role"] == "approver"

    decisions = [e for e in body["entries"] if e["action"] == "CASE_APPROVED"]
    assert sorted(e["case_id"] for e in decisions) == sorted(c["case_id"] for c in queue(ran))
    assert {e["actor"] for e in decisions} == {"analyst1", "approver1"}


def test_trail_stops_where_the_next_day_begins(ran, make_client, factory, day_files):  # noqa: F811
    decide_all(ran, make_client("approver1"))
    assert make_client("approver2").post(f"{DAY_URL}/signoff").status_code == 200
    day1_before = trail(ran)
    run_day(ran, factory, day_files[1], as_of=DAY2)

    day1 = trail(ran)
    assert day1["entries"] == day1_before["entries"]  # nothing of day 2 joins day 1's trail
    day2 = trail(ran, DAY2)
    got = actions(day2)
    assert got[0] == "FILES_UPLOADED" and got[-1] == "RUN_FINISHED"
    assert day2["entries"][0]["seq"] > day1["entries"][-1]["seq"]
    assert all(e["payload"].get("as_of", str(DAY2)) == str(DAY2) for e in day2["entries"])


def test_trail_leaves_out_other_funds(ran, make_client, make_fund, day_files):  # noqa: F811
    make_fund(code="INC2", name="Income Fund")
    parts = [("files", (FILE_KINDS[kind], content, "text/csv")) for kind, content in day_files[0].items()]
    assert ran.post(f"/api/funds/INC2/days/{DAY1}/files", files=parts).status_code == 200
    gef1 = trail(ran)
    inc2 = trail(ran, code="INC2")
    assert actions(inc2) == ["FILES_UPLOADED", "VALIDATION_PASSED"]
    assert not {e["seq"] for e in inc2["entries"]} & {e["seq"] for e in gef1["entries"]}


def test_trail_reports_a_broken_chain(ran, db_engine):  # noqa: F811
    seq = trail(ran)["entries"][1]["seq"]
    with db_engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
        conn.execute(text("UPDATE audit_log SET actor = 'someone-else' WHERE seq = :seq"), {"seq": seq})
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    body = trail(ran)
    assert body["chain_ok"] is False and body["broken_at"] == seq
