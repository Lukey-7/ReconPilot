"""Uploading a day's files: storage, validation, day ordering and roles."""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import select

from reconpilot_web.auditlog import DbAuditLog, verify_chain
from reconpilot_web.models import BusinessDay, InputFile
from reconpilot_web.validation import FILE_KINDS

from .conftest import FUND_CODE, FUND_START

DAY1, DAY2 = FUND_START, date(2026, 11, 10)


def upload(client, files: dict[str, bytes], as_of: date = DAY1, names: dict[str, str] | None = None):
    names = names or {}
    parts = [("files", (names.get(kind, FILE_KINDS[kind]), content, "text/csv")) for kind, content in files.items()]
    return client.post(f"/api/funds/{FUND_CODE}/days/{as_of}/files", files=parts)


def _actions(db_session) -> list[str]:
    return [e["action"] for e in DbAuditLog(db_session).entries()]


def _sign_off(db_session, fund, as_of: date) -> None:
    """Mark a day signed off directly (the sign-off route is built separately)."""
    day = db_session.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of == as_of)
    ).scalar_one()
    day.status = "signed_off"
    db_session.commit()


def test_valid_day_uploads_and_validates(make_client, users, fund, day_files, db_session):
    analyst = make_client("analyst1")
    response = upload(analyst, day_files[0])
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "validated", "errors": [], "warnings": []}

    stored = db_session.execute(select(InputFile)).scalars().all()
    assert {f.kind for f in stored} == set(FILE_KINDS)
    for f in stored:
        assert bytes(f.content) == day_files[0][f.kind]
        assert f.sha256 == hashlib.sha256(day_files[0][f.kind]).hexdigest()
        assert f.size_bytes == len(day_files[0][f.kind])

    day = analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").json()
    assert day["status"] == "validated" and day["previous_business_day"] is None
    assert [f["kind"] for f in day["files"]] == list(FILE_KINDS)
    assert {f["uploaded_by"] for f in day["files"]} == {"analyst1"}
    assert day["validation"] == {"errors": [], "warnings": []}
    assert day["nav"] is None and day["release"] is None  # not run yet

    assert _actions(db_session)[-2:] == ["FILES_UPLOADED", "VALIDATION_PASSED"]
    uploaded = DbAuditLog(db_session).entries()[-2]["payload"]
    assert uploaded["as_of"] == str(DAY1)
    assert {f["kind"]: f["sha256"] for f in uploaded["files"]} == {
        k: hashlib.sha256(v).hexdigest() for k, v in day_files[0].items()
    }
    assert verify_chain(db_session) == (True, None)


def test_errors_leave_day_uploaded_and_later_upload_fixes_it(make_client, users, fund, day_files, db_session):
    analyst = make_client("analyst1")
    partial = {k: v for k, v in day_files[0].items() if k != "positions"}
    response = upload(analyst, partial)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["errors"] == [{"file": "book_positions.csv", "row": None, "message": "Required file is missing."}]
    assert _actions(db_session)[-1] == "VALIDATION_FAILED"

    # Sending the missing file alone validates the whole day again.
    response = upload(analyst, {"positions": day_files[0]["positions"]})
    assert response.json() == {"status": "validated", "errors": [], "warnings": []}


def test_reupload_replaces_file_of_same_kind(make_client, users, fund, day_files, db_session):
    analyst = make_client("analyst1")
    upload(analyst, day_files[0])
    changed = day_files[0]["trades"].replace(b"BUY", b"HOLD", 1)
    response = upload(analyst, {"trades": changed}, names={"trades": "Book_Trades.CSV"})
    assert response.json()["status"] == "uploaded"
    assert "side 'HOLD' must be BUY or SELL." in response.json()["errors"][0]["message"]
    rows = db_session.execute(select(InputFile).where(InputFile.kind == "trades")).scalars().all()
    assert len(rows) == 1 and bytes(rows[0].content) == changed and rows[0].filename == "Book_Trades.CSV"


def test_bom_and_crlf_accepted(make_client, users, fund, day_files, db_session):
    """Review focus 2: files saved by Excel (byte-order mark, CRLF) validate like any other."""
    excel = {
        kind: b"\xef\xbb\xbf" + content.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        for kind, content in day_files[0].items()
    }
    response = upload(make_client("analyst1"), excel)
    assert response.json() == {"status": "validated", "errors": [], "warnings": []}
    stored = db_session.execute(select(InputFile).where(InputFile.kind == "fund")).scalar_one()
    assert bytes(stored.content) == excel["fund"]  # kept byte for byte


def test_upload_refused_until_previous_day_signed_off(make_client, users, fund, day_files, db_session):
    analyst = make_client("analyst1")
    response = upload(analyst, day_files[1], as_of=DAY2)
    assert response.status_code == 409
    assert response.json()["detail"] == f"Sign off {DAY1} first."

    assert upload(analyst, day_files[0]).json()["status"] == "validated"
    response = upload(analyst, day_files[1], as_of=DAY2)
    assert response.status_code == 409 and response.json()["detail"] == f"Sign off {DAY1} first."

    _sign_off(db_session, fund, DAY1)
    response = upload(analyst, day_files[1], as_of=DAY2)
    assert response.status_code == 200 and response.json()["status"] == "validated"
    assert analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY2}").json()["previous_business_day"] == str(DAY1)

    # A signed-off day's files never change.
    response = upload(analyst, day_files[0])
    assert response.status_code == 409 and "signed off" in response.json()["detail"]
    # Nothing was stored for the refused uploads.
    assert db_session.query(BusinessDay).count() == 2


def test_upload_refused_before_start_or_on_non_business_day(make_client, users, make_fund, day_files):
    make_fund(non_business_dates=[date(2026, 11, 11)])
    analyst = make_client("analyst1")
    assert upload(analyst, day_files[0], as_of=date(2026, 11, 6)).status_code == 409
    response = upload(analyst, day_files[0], as_of=date(2026, 11, 14))
    assert response.status_code == 409 and response.json()["detail"] == f"2026-11-14 is not a business day for {FUND_CODE}."
    assert upload(analyst, day_files[0], as_of=date(2026, 11, 11)).status_code == 409


def test_viewer_cannot_upload(make_client, users, fund, day_files, client):
    assert upload(make_client("viewer1"), day_files[0]).status_code == 403
    assert upload(client, day_files[0]).status_code == 403  # signed out: refused by the CSRF guard first
    assert upload(make_client("approver1"), day_files[0]).status_code == 200


def test_upload_needs_csrf_token(make_client, users, fund, day_files):
    analyst = make_client("analyst1")
    del analyst.headers["X-CSRF-Token"]
    assert upload(analyst, day_files[0]).status_code == 403


def test_unknown_or_repeated_filenames_refused(make_client, users, fund, day_files, db_session):
    analyst = make_client("analyst1")
    response = upload(analyst, {"trades": day_files[0]["trades"]}, names={"trades": "planted_breaks.json"})
    assert response.status_code == 422 and "planted_breaks.json" in response.json()["detail"]
    parts = [("files", ("book_trades.csv", day_files[0]["trades"], "text/csv"))] * 2
    response = analyst.post(f"/api/funds/{FUND_CODE}/days/{DAY1}/files", files=parts)
    assert response.status_code == 422 and "more than once" in response.json()["detail"]
    assert db_session.query(InputFile).count() == 0


def test_bad_date_and_unknown_fund(make_client, users, fund, day_files):
    analyst = make_client("analyst1")
    assert analyst.post(f"/api/funds/{FUND_CODE}/days/20261109/files",
                        files=[("files", ("fund.csv", day_files[0]["fund"], "text/csv"))]).status_code == 422
    assert analyst.post(f"/api/funds/NOPE/days/{DAY1}/files",
                        files=[("files", ("fund.csv", day_files[0]["fund"], "text/csv"))]).status_code == 404
    assert analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").status_code == 404


def test_viewer_can_read_day(make_client, users, fund, day_files):
    upload(make_client("analyst1"), day_files[0])
    response = make_client("viewer1").get(f"/api/funds/{FUND_CODE}/days/{DAY1}")
    assert response.status_code == 200 and response.json()["status"] == "validated"


def test_oversized_file_refused_before_storing(make_client, users, fund, day_files, db_session):
    from reconpilot_web.validation import MAX_FILE_BYTES

    big = day_files[0]["prior_prices"] + b"X" * MAX_FILE_BYTES
    response = upload(make_client("analyst1"), {**day_files[0], "prior_prices": big})
    assert response.status_code == 413 and "prior_prices.csv" in response.json()["detail"]
    assert db_session.query(InputFile).count() == 0 and db_session.query(BusinessDay).count() == 0
