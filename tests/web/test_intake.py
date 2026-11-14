"""Whether a day can take files (and why not, in the upload route's own words), and the day's runs."""

from __future__ import annotations

import dataclasses
from datetime import date

from reconpilot_web import runner
from reconpilot_web.validation import FILE_KINDS, MAX_FILE_BYTES, MAX_ROWS, REQUIRED

from .conftest import FUND_CODE, FUND_START
from .test_runner import factory, no_backoff, sign_off, start_run, upload_and_run, work  # noqa: F401
from .test_upload import upload

DAY1, DAY2, DAY3 = FUND_START, date(2026, 11, 10), date(2026, 11, 11)


def intake(client, as_of, code: str = FUND_CODE):
    response = client.get(f"/api/funds/{code}/days/{as_of}/intake")
    assert response.status_code == 200, response.text
    return response.json()


def runs(client, as_of=DAY1):
    response = client.get(f"/api/funds/{FUND_CODE}/days/{as_of}/runs")
    assert response.status_code == 200, response.text
    return response.json()["runs"]


# --------------------------------------------------------------------------- intake


def test_intake_needs_sign_in_and_a_real_day(client, make_client, users, fund):
    assert client.get(f"/api/funds/{FUND_CODE}/days/{DAY1}/intake").status_code == 401
    viewer = make_client("viewer1")
    assert viewer.get(f"/api/funds/{FUND_CODE}/days/2026-13-01/intake").status_code == 422
    assert viewer.get(f"/api/funds/NOPE/days/{DAY1}/intake").status_code == 404


def test_first_day_is_open_and_lists_the_files_it_expects(make_client, users, fund):
    body = intake(make_client("viewer1"), DAY1)
    assert body == {
        "fund": FUND_CODE,
        "as_of": str(DAY1),
        "open": True,
        "blocked": None,
        "day_status": None,
        "previous_business_day": None,
        "previous_status": None,
        "following_day": str(DAY2),
        "expected_files": [
            {"kind": kind, "filename": name, "required": kind in REQUIRED} for kind, name in FILE_KINDS.items()
        ],
        "max_file_bytes": MAX_FILE_BYTES,
        "max_rows": MAX_ROWS,
    }
    assert {f["filename"] for f in body["expected_files"] if f["required"]} >= {"book_trades.csv", "fund.csv"}


def test_before_start_and_non_business_days(make_client, users, make_fund):
    make_fund(non_business_dates=[DAY3])
    viewer = make_client("viewer1")
    before = intake(viewer, date(2026, 11, 6))
    assert before["open"] is False
    assert before["blocked"] == {
        "code": "BEFORE_START", "message": f"2026-11-06 is before {FUND_CODE}'s start date, {FUND_START}.",
        "day": str(FUND_START), "day_status": None,
    }
    saturday = intake(viewer, date(2026, 11, 14))["blocked"]
    assert saturday["code"] == "NOT_BUSINESS_DAY" and saturday["day"] == "2026-11-14"
    holiday = intake(viewer, DAY3)
    assert holiday["blocked"]["code"] == "NOT_BUSINESS_DAY"
    # The day after Tuesday is Thursday: Wednesday is a holiday.
    assert intake(viewer, DAY2)["following_day"] == "2026-11-12"
    assert intake(viewer, date(2026, 11, 13))["following_day"] == "2026-11-16"


def test_previous_day_must_be_loaded_and_signed_off(make_client, users, fund, day_files, factory, db_session):
    analyst = make_client("analyst1")
    nothing = intake(analyst, DAY2)
    assert nothing["open"] is False and nothing["previous_status"] is None
    assert nothing["blocked"] == {
        "code": "PREVIOUS_NOT_LOADED", "message": f"Sign off {DAY1} first.", "day": str(DAY1), "day_status": None,
    }

    upload_and_run(analyst, factory, day_files[0])
    waiting = intake(analyst, DAY2)
    assert waiting["blocked"] == {
        "code": "PREVIOUS_NOT_SIGNED_OFF", "message": f"Sign off {DAY1} first.", "day": str(DAY1),
        "day_status": "ready",
    }
    assert waiting["previous_business_day"] == str(DAY1) and waiting["previous_status"] == "ready"
    # The upload route refuses for the same reason, in the same words.
    refused = upload(analyst, day_files[1], as_of=DAY2)
    assert refused.status_code == 409 and refused.json()["detail"] == waiting["blocked"]["message"]
    # The day that is loaded and not signed off still takes files.
    assert intake(analyst, DAY1)["open"] is True

    sign_off(db_session, fund, DAY1)
    assert intake(analyst, DAY2)["open"] is True
    locked = intake(analyst, DAY1)
    assert locked["day_status"] == "signed_off"
    assert locked["blocked"] == {
        "code": "SIGNED_OFF", "message": f"{DAY1} is signed off; its files cannot change.", "day": str(DAY1),
        "day_status": "signed_off",
    }
    refused = upload(analyst, day_files[0], as_of=DAY1)
    assert refused.status_code == 409 and refused.json()["detail"] == locked["blocked"]["message"]


def test_running_day_takes_no_files(make_client, users, fund, day_files, factory):
    analyst = make_client("analyst1")
    assert upload(analyst, day_files[0]).json()["status"] == "validated"
    assert start_run(analyst).status_code == 202
    body = intake(analyst, DAY1)
    assert body["open"] is False and body["day_status"] == "running"
    assert body["blocked"]["code"] == "RUNNING"
    refused = upload(analyst, day_files[0])
    assert refused.status_code == 409 and refused.json()["detail"] == body["blocked"]["message"]
    work(factory)
    assert intake(analyst, DAY1)["open"] is True


def test_demo_instance_takes_no_files(make_client, users, fund, app, settings, day_files):
    analyst = make_client("analyst1")
    app.state.settings = dataclasses.replace(settings, mode="demo")
    body = intake(analyst, DAY1)
    assert body["open"] is False and body["blocked"]["code"] == "UPLOADS_OFF"
    refused = upload(analyst, day_files[0])
    assert refused.status_code == 403 and refused.json()["detail"] == body["blocked"]["message"]


# --------------------------------------------------------------------------- runs


def test_runs_need_files(client, make_client, users, fund):
    assert client.get(f"/api/funds/{FUND_CODE}/days/{DAY1}/runs").status_code == 401
    assert make_client("viewer1").get(f"/api/funds/{FUND_CODE}/days/{DAY1}/runs").status_code == 404


def test_runs_listed_newest_first_with_what_they_found(make_client, users, fund, day_files, factory):
    analyst = make_client("analyst1")
    assert upload(analyst, day_files[0]).json()["status"] == "validated"
    assert runs(analyst) == []

    first = upload_and_run(analyst, factory, day_files[0])
    day = analyst.get(f"/api/funds/{FUND_CODE}/days/{DAY1}").json()
    [run] = runs(make_client("viewer1"))
    assert run["job_id"] == first and run["status"] == "done"
    assert run["started_by"] == "analyst1" and run["rerun"] is False
    assert run["attempts"] == 1 and run["max_attempts"] == 3 and run["error"] is None and run["skipped"] is None
    assert run["queued_at"] and run["started_at"] and run["finished_at"]
    assert run["duration_seconds"] is not None and run["duration_seconds"] >= 0
    summary = day["summary"]
    assert run["outcome"] == {
        "open_cases": summary["open_cases"], "new_cases": summary["new_cases"],
        "carried_cases": summary["carried_cases"], "cleared_today": len(summary["cleared_today"]),
        "breaks": summary["breaks"], "matches": summary["matches"],
        "decisions_reapplied": 0, "decisions_voided": 0, "cases_withdrawn": 0,
    }

    approver = make_client("approver1")
    second = start_run(approver).json()["job_id"]
    queued, done = runs(analyst)
    assert (queued["job_id"], done["job_id"]) == (second, first)
    assert queued["status"] == "queued" and queued["outcome"] is None and queued["finished_at"] is None
    assert queued["started_by"] == "approver1" and queued["rerun"] is True
    work(factory)
    assert runs(analyst)[0]["status"] == "done" and runs(analyst)[0]["outcome"]["open_cases"] == summary["open_cases"]


def test_failed_run_shows_its_error(make_client, users, fund, day_files, factory, monkeypatch, no_backoff):
    def explode(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(runner, "run_day", explode)
    analyst = make_client("analyst1")
    assert upload(analyst, day_files[0]).json()["status"] == "validated"
    job_id = start_run(analyst).json()["job_id"]
    work(factory)
    [retrying] = runs(analyst)
    assert retrying["status"] == "queued" and retrying["attempts"] == 1
    assert retrying["error"] == "RuntimeError: disk on fire"
    work(factory)
    work(factory)
    [failed] = runs(analyst)
    assert failed["job_id"] == job_id and failed["status"] == "failed" and failed["attempts"] == 3
    assert failed["error"] == "RuntimeError: disk on fire" and failed["outcome"] is None
