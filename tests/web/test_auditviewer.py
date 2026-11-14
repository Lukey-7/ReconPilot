"""The audit log viewer: filters, pages, one entry, chain verification and the CSV export."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from reconpilot.audit import GENESIS, record_hash
from reconpilot_web import auditviewer
from reconpilot_web.auditlog import DbAuditLog
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

URL = "/api/audit"


def page(client, **params) -> dict:
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def every(client, **params) -> list[dict]:
    """Every matching entry, newest first, walking the pages with ``next_before``."""
    out: list[dict] = []
    before = None
    while True:
        body = page(client, **params, **({"before": before} if before else {}))
        out.extend(body["entries"])
        before = body["next_before"]
        if before is None:
            return out


def actions(entries: list[dict]) -> list[str]:
    return [e["action"] for e in entries]


def tamper(db_engine, seq: int, sql: str = "UPDATE audit_log SET actor = 'someone-else' WHERE seq = :seq") -> None:
    with db_engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
        conn.execute(text(sql), {"seq": seq})
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))


def signed_off_and_day2(ran, make_client, factory, day_files) -> None:  # noqa: F811
    """Day 1 decided and signed off by ``approver2``, then day 2 uploaded and run."""
    decide_all(ran, make_client("approver1"))
    assert make_client("approver2").post(f"{DAY_URL}/signoff").status_code == 200
    run_day(ran, factory, day_files[1], as_of=DAY2)


# --------------------------------------------------------------------------- access


def test_needs_sign_in(client, users):
    for path in (URL, f"{URL}/facets", f"{URL}/entries/1", f"{URL}/export.csv"):
        assert client.get(path).status_code == 401, path
    assert client.post(f"{URL}/verify").status_code in (401, 403)


@pytest.mark.parametrize("role_user", ["analyst1", "approver1", "viewer1"])
def test_every_role_may_read_verify_and_export(make_client, users, fund, role_user):
    client = make_client(role_user)
    body = page(client)
    assert body["total"] >= 1 and body["latest_seq"] == body["entries"][0]["seq"]
    assert client.post(f"{URL}/verify").status_code == 200
    assert client.get(f"{URL}/export.csv").status_code == 200
    assert client.get(f"{URL}/entries/1").status_code == 200


def test_verify_needs_the_csrf_token(make_client, users):
    client = make_client("viewer1")
    del client.headers["X-CSRF-Token"]
    assert client.post(f"{URL}/verify").status_code == 403


# --------------------------------------------------------------------------- the list and its filters


def test_entries_newest_first_with_fund_codes(ran, make_client):  # noqa: F811
    body = page(ran)
    seqs = [e["seq"] for e in body["entries"]]
    assert seqs == sorted(seqs, reverse=True)
    assert body["total"] == len(seqs) and body["next_before"] is None and body["newer"] == 0
    assert body["has_newer"] is False and body["newer_before"] is None
    entry = body["entries"][0]
    assert set(entry) == {"seq", "ts", "actor", "role", "action", "fund", "case_id", "payload", "prev_hash", "hash"}
    by_action = {e["action"]: e for e in body["entries"]}
    assert by_action["RUN_FINISHED"]["fund"] == FUND_CODE
    assert by_action["SIGN_IN"]["fund"] is None  # a system entry, in the log all the same
    assert by_action["USER_CREATED"]["fund"] is None


def test_fund_filter_and_unknown_fund(ran, make_client, make_fund, day_files):  # noqa: F811
    make_fund(code="INC2", name="Income Fund")
    parts = [("files", (FILE_KINDS[kind], content, "text/csv")) for kind, content in day_files[0].items()]
    assert ran.post(f"/api/funds/INC2/days/{DAY1}/files", files=parts).status_code == 200
    gef1 = every(ran, fund=FUND_CODE)
    inc2 = every(ran, fund="inc2")  # codes are case-insensitive, as everywhere
    assert {e["fund"] for e in gef1} == {FUND_CODE}
    assert actions(inc2) == ["VALIDATION_PASSED", "FILES_UPLOADED", "FUND_CREATED"]
    assert len(every(ran)) > len(gef1) + len(inc2)  # sign-ins and users belong to no fund
    response = ran.get(URL, params={"fund": "NOPE"})
    assert response.status_code == 404


def test_business_day_filter_matches_the_day_trail(ran, make_client, factory, day_files):  # noqa: F811
    signed_off_and_day2(ran, make_client, factory, day_files)
    for as_of in (DAY1, DAY2):
        trail = ran.get(f"/api/funds/{FUND_CODE}/days/{as_of}/audit").json()["entries"]
        listed = every(ran, fund=FUND_CODE, as_of=str(as_of))
        assert [e["seq"] for e in reversed(listed)] == [e["seq"] for e in trail]
    # A day with nothing recorded matches nothing; a day without a fund is refused.
    assert page(ran, fund=FUND_CODE, as_of="2026-11-20")["total"] == 0
    response = ran.get(URL, params={"as_of": str(DAY1)})
    assert response.status_code == 422 and "needs a fund" in response.json()["detail"]
    assert ran.get(URL, params={"fund": FUND_CODE, "as_of": "nope"}).status_code == 422


def test_date_range_by_day_and_by_instant(ran):  # noqa: F811
    entries = every(ran)
    today = datetime.fromisoformat(entries[0]["ts"]).date()
    assert len(every(ran, **{"from": str(today), "to": str(today)})) == len(entries)
    assert page(ran, **{"from": str(today + timedelta(days=1))})["total"] == 0
    assert page(ran, to=str(today - timedelta(days=1)))["total"] == 0

    # Instants with an offset: the entries' own times, as a browser sends a local day.
    middle = entries[len(entries) // 2]
    moment = datetime.fromisoformat(middle["ts"])
    later = every(ran, **{"from": moment.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()})
    assert all(e["ts"] >= middle["ts"] for e in later) and middle["seq"] in {e["seq"] for e in later}
    earlier = every(ran, to=moment.isoformat())
    assert all(e["ts"] <= middle["ts"] for e in earlier) and middle["seq"] in {e["seq"] for e in earlier}
    # As a browser writes the end of a day: UTC with milliseconds.
    end = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.999Z")
    assert [e["seq"] for e in every(ran, to=end)] == [e["seq"] for e in earlier]

    bad_filters = ({"from": "yesterday"}, {"to": "2026-11-14T10:00:00"},
                   {"from": str(today), "to": str(today - timedelta(days=1))})
    for bad in bad_filters:
        assert ran.get(URL, params=bad).status_code == 422, bad


def test_actor_action_and_case_filters(ran, make_client):  # noqa: F811
    approver = make_client("approver1")
    decide_all(ran, approver)
    cases = {c["case_id"] for c in queue(ran)}

    mine = every(ran, actor="ANALYST1")
    assert mine and {e["actor"] for e in mine} == {"analyst1"}

    decisions = every(ran, action="case_approved,CASE_REJECTED")
    assert set(actions(decisions)) == {"CASE_APPROVED"}
    assert {e["case_id"] for e in decisions} == cases

    case_id = sorted(cases)[0]
    history = every(ran, case=case_id.lower())
    assert history and {e["case_id"] for e in history} == {case_id}
    assert "CASE_APPROVED" in actions(history)

    combined = every(ran, fund=FUND_CODE, actor="approver1", action="CASE_APPROVED")
    assert combined and all(e["actor"] == "approver1" for e in combined)
    assert {e["case_id"] for e in combined} <= cases

    assert ran.get(URL, params={"action": "DROP TABLE"}).status_code == 422
    assert ran.get(URL, params={"limit": 0}).status_code == 422
    assert ran.get(URL, params={"limit": 201}).status_code == 422


def test_facets(ran, make_client, make_fund):  # noqa: F811
    make_fund(code="INC2", name="Income Fund")
    body = ran.get(f"{URL}/facets").json()
    assert body["actors"] == sorted(body["actors"]) and "analyst1" in body["actors"]
    assert {"SIGN_IN", "RUN_FINISHED", "FUND_CREATED"} <= set(body["actions"])
    fund_only = ran.get(f"{URL}/facets", params={"fund": FUND_CODE}).json()
    assert "SIGN_IN" not in fund_only["actions"] and "RUN_FINISHED" in fund_only["actions"]
    assert ran.get(f"{URL}/facets", params={"fund": "NOPE"}).status_code == 404


def test_pages_cover_every_entry_once(ran):  # noqa: F811
    everything = page(ran, limit=200)["entries"]
    total = len(everything)
    assert total > 7, "a run day writes more than a couple of pages of three"

    seen: list[int] = []
    pages: list[dict] = []
    before = None
    while True:
        body = page(ran, limit=3, **({"before": before} if before else {}))
        pages.append(body)
        assert body["total"] == total
        assert body["newer"] == len(seen)
        seen.extend(e["seq"] for e in body["entries"])
        before = body["next_before"]
        if before is None:
            break
    assert seen == [e["seq"] for e in everything]
    assert all(len(p["entries"]) == 3 for p in pages[:-1])

    # Each page's newer cursor opens exactly the page before it.
    for previous, current in zip(pages, pages[1:]):
        assert current["has_newer"] is True
        params = {"limit": 3, **({"before": current["newer_before"]} if current["newer_before"] else {})}
        assert page(ran, **params)["entries"] == previous["entries"]
    assert pages[1]["newer_before"] is None  # the page above the second is the first


# --------------------------------------------------------------------------- one entry


def test_one_entry_with_its_integrity(ran, db_engine):  # noqa: F811
    first = ran.get(f"{URL}/entries/1").json()
    assert first["prev_hash"] == GENESIS and first["hash_ok"] is True and first["linked"] is True
    latest = page(ran)["entries"][0]
    entry = ran.get(f"{URL}/entries/{latest['seq']}").json()
    assert {k: entry[k] for k in latest} == latest
    assert entry["hash_ok"] is True and entry["linked"] is True
    assert ran.get(f"{URL}/entries/999999").status_code == 404

    tamper(db_engine, 3)
    assert ran.get(f"{URL}/entries/3").json()["hash_ok"] is False
    assert ran.get(f"{URL}/entries/4").json()["linked"] is True  # it still names 3's stored hash
    tamper(db_engine, 5, "UPDATE audit_log SET hash = repeat('a', 64) WHERE seq = :seq")
    assert ran.get(f"{URL}/entries/6").json()["linked"] is False


# --------------------------------------------------------------------------- verification


def test_verify_intact_and_recorded(ran, make_client, db_session):  # noqa: F811
    viewer = make_client("viewer1")
    before = page(ran)["latest_seq"]
    response = viewer.post(f"{URL}/verify")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["chain_ok"] is True and body["broken_at"] is None
    assert body["entries"] == body["last_seq"] == before
    assert body["seq"] == before + 1 and body["verified_by"] == "viewer1"

    entry = ran.get(f"{URL}/entries/{body['seq']}").json()
    assert entry["action"] == "AUDIT_CHAIN_VERIFIED" and entry["actor"] == "viewer1" and entry["fund"] is None
    assert entry["payload"] == {"intact": True, "broken_at": None, "entries": before, "last_seq": before}
    assert entry["prev_hash"] == body["last_hash"] and entry["ts"] == body["verified_at"]
    db_session.expire_all()
    assert DbAuditLog(db_session).verify() == (True, None)


def test_verify_reports_the_first_broken_entry(ran, db_engine):  # noqa: F811
    tamper(db_engine, 4)
    tamper(db_engine, 7)
    body = ran.post(f"{URL}/verify").json()
    assert body["chain_ok"] is False and body["broken_at"] == 4
    entry = ran.get(f"{URL}/entries/{body['seq']}").json()
    assert entry["payload"]["intact"] is False and entry["payload"]["broken_at"] == 4


# --------------------------------------------------------------------------- the CSV export


def read_csv(content: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"), newline="")))


def test_export_rehashes_and_reverifies(ran, make_client):  # noqa: F811
    decide_all(ran, make_client("approver1"))
    viewer = make_client("viewer1")
    response = viewer.get(f"{URL}/export.csv")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    today = datetime.now(timezone.utc).date()
    assert response.headers["content-disposition"] == f'attachment; filename="audit_ALL_{today}.csv"'
    assert response.content.decode("utf-8").split("\r\n")[0] == ",".join(auditviewer.CSV_COLUMNS)

    rows = read_csv(response.content)
    prev = GENESIS
    for i, row in enumerate(rows, start=1):
        record = {"seq": int(row["seq"]), "ts": row["ts"], "actor": row["actor"], "role": row["role"],
                  "action": row["action"], "payload": json.loads(row["payload"]), "prev_hash": row["prev_hash"]}
        assert record["seq"] == i and record["prev_hash"] == prev
        assert record_hash(record) == row["hash"], row["seq"]
        prev = row["hash"]
    assert {r["fund"] for r in rows} == {"", FUND_CODE}


def test_export_filtered_and_audited(ran, make_client, db_session, make_fund):  # noqa: F811
    approver = make_client("approver1")
    decide_all(ran, approver)
    response = approver.get(f"{URL}/export.csv", params={"fund": FUND_CODE, "action": "CASE_APPROVED"})
    assert response.status_code == 200
    filename = f"audit_{FUND_CODE}_{datetime.now(timezone.utc).date()}.csv"
    assert filename in response.headers["content-disposition"]
    rows = read_csv(response.content)
    assert rows and {r["action"] for r in rows} == {"CASE_APPROVED"}
    assert [int(r["seq"]) for r in rows] == sorted(int(r["seq"]) for r in rows)  # chain order
    assert len(rows) == len(queue(ran))

    exported = page(ran, action="EXPORT_DOWNLOADED")["entries"][0]
    assert exported["actor"] == "approver1" and exported["fund"] == FUND_CODE
    assert exported["payload"] == {
        "export": "audit_csv",
        "filename": filename,
        "bytes": len(response.content),
        "sha256": hashlib.sha256(response.content).hexdigest(),
        "rows": len(rows),
        "filters": {"fund": FUND_CODE, "action": "CASE_APPROVED"},
    }
    # An export of every fund is recorded against none.
    assert approver.get(f"{URL}/export.csv").status_code == 200
    assert page(ran, action="EXPORT_DOWNLOADED")["entries"][0]["fund"] is None
    # Bad filters are refused before anything is written.
    total = page(ran)["total"]
    assert approver.get(f"{URL}/export.csv", params={"fund": "NOPE"}).status_code == 404
    assert approver.get(f"{URL}/export.csv", params={"from": "nope"}).status_code == 422
    assert page(ran)["total"] == total


def test_export_refuses_more_than_the_cap(ran, monkeypatch):  # noqa: F811
    monkeypatch.setattr(auditviewer, "MAX_EXPORT_ROWS", 3)
    total = page(ran)["total"]
    response = ran.get(f"{URL}/export.csv")
    assert response.status_code == 422 and "Narrow the filters" in response.json()["detail"]
    assert page(ran)["total"] == total  # a refused export is not recorded as downloaded
    assert ran.get(f"{URL}/export.csv", params={"action": "RUN_FINISHED"}).status_code == 200


def test_entries_of_a_removed_fund_keep_their_place(ran, db_engine):  # noqa: F811
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM funds WHERE code = :code"), {"code": FUND_CODE})
    entries = every(ran)
    assert any(e["action"] == "RUN_FINISHED" and e["fund"] is None for e in entries)
    assert ran.post(f"{URL}/verify").json()["chain_ok"] is True

