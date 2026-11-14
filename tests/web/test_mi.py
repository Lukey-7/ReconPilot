"""Management information across days and the audited exports (spec section 10, screen 5)."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date

from openpyxl import load_workbook

from reconpilot.mi import MI_COLUMNS, build_mi
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.mi import ledger_history
from reconpilot_web.models import Fund

from .conftest import FUND_CODE
from .test_release import (
    DAY1,
    DAY2,
    factory,  # noqa: F401  (fixture)
    queue,
    ran,  # noqa: F401  (fixture)
    run_day,
)
from .test_upload import upload

DAYS_URL = f"/api/funds/{FUND_CODE}/days"
DAY3 = date(2026, 11, 11)


def mi(client, as_of: date = DAY1) -> dict:
    response = client.get(f"{DAYS_URL}/{as_of}/mi")
    assert response.status_code == 200, response.text
    return response.json()


def sign_off(analyst, make_client, as_of: date) -> None:
    """Decide the day's cases (the approver takes escalated ones) and sign off as ``approver2``."""
    approver = make_client("approver1")
    for case in queue(analyst, as_of):
        if case["status"] != "PENDING" and not case["escalated"]:
            continue  # carried with its decision
        client = approver if case["escalated"] else analyst
        response = client.post(f"/api/funds/{FUND_CODE}/cases/{case['case_id']}/decision",
                               json={"decision": "approve", "version": case["version"]})
        assert response.status_code == 200, response.text
    response = make_client("approver2").post(f"{DAYS_URL}/{as_of}/signoff")
    assert response.status_code == 200, response.text


def three_days(analyst, make_client, factory, day_files) -> None:  # noqa: F811
    """Days 1 and 2 run and signed off, day 3 run."""
    sign_off(analyst, make_client, DAY1)
    run_day(analyst, factory, day_files[1], as_of=DAY2)
    sign_off(analyst, make_client, DAY2)
    run_day(analyst, factory, day_files[2], as_of=DAY3)


def exports(db_session) -> list[dict]:
    db_session.expire_all()
    return [e for e in DbAuditLog(db_session).entries() if e["action"] == "EXPORT_DOWNLOADED"]


# --------------------------------------------------------------------------- access and shape


def test_mi_requires_sign_in_and_a_day(client, make_client, users, fund):
    assert client.get(f"{DAYS_URL}/{DAY1}/mi").status_code == 401
    assert client.get(f"{DAYS_URL}/{DAY1}/exports/mi.csv").status_code == 401
    assert client.get(f"{DAYS_URL}/{DAY1}/exports/report.xlsx").status_code == 401
    viewer = make_client("viewer1")
    assert viewer.get(f"{DAYS_URL}/{DAY1}/mi").status_code == 404
    assert viewer.get(f"{DAYS_URL}/{DAY1}/exports/mi.csv").status_code == 404
    assert viewer.get(f"{DAYS_URL}/not-a-date/mi").status_code == 422
    assert viewer.get(f"/api/funds/NOPE/days/{DAY1}/mi").status_code == 404


def test_mi_before_the_run(make_client, users, fund, day_files, db_session):
    analyst = make_client("analyst1")
    assert upload(analyst, day_files[0]).json()["status"] == "validated"
    body = mi(analyst)
    assert body["has_run"] is False and body["day_status"] == "validated" and body["run_days"] == 0
    assert body["exports"] is None
    assert body["top_open"] == body["sla_breaches"] == body["trend"] == []
    assert body["by_cause_age"]["rows"] == []
    assert body["by_cause_age"]["buckets"] == ["0-1", "2-5", ">5"]
    assert body["by_cause_age"]["total"]["count"] == 0
    assert [c["count"] for c in body["by_cause_age"]["total"]["cells"]] == [0, 0, 0]
    assert body["time_to_resolve"] == {"rows": [], "all": {"cleared": 0, "avg_days": None}}
    for name in ("report.xlsx", "mi.csv"):
        response = analyst.get(f"{DAYS_URL}/{DAY1}/exports/{name}")
        assert response.status_code == 409 and "run the day first" in response.json()["detail"]
    assert exports(db_session) == []


def test_open_breaks_by_cause_and_age_with_gross_and_net(ran):  # noqa: F811
    body = mi(ran)
    overview = ran.get(f"{DAYS_URL}/{DAY1}/overview").json()
    grid = body["by_cause_age"]
    total = grid["total"]
    assert body["has_run"] is True and body["run_days"] == 1
    assert total["count"] == len(queue(ran)) == overview["accounted"]["open_cases"]
    assert total["net"] == overview["impact"]["net"] and total["gross"] == overview["impact"]["gross"]
    assert total["gross"] >= abs(total["net"])
    assert [r["cause"] for r in grid["rows"]], "the generated day has open cases"
    for block in (*grid["rows"], total):
        assert [c["bucket"] for c in block["cells"]] == ["0-1", "2-5", ">5"]
        assert block["count"] == sum(c["count"] for c in block["cells"])
        assert block["net"] == round(sum(c["net"] for c in block["cells"]), 2)
        assert block["gross"] == round(sum(c["gross"] for c in block["cells"]), 2)
    assert total["count"] == sum(r["count"] for r in grid["rows"])
    for i, cell in enumerate(total["cells"]):
        assert cell["count"] == sum(r["cells"][i]["count"] for r in grid["rows"])
    assert body["exports"] == {"report": f"{DAYS_URL}/{DAY1}/exports/report.xlsx",
                               "mi_csv": f"{DAYS_URL}/{DAY1}/exports/mi.csv"}


def test_top_five_open_by_absolute_impact(ran):  # noqa: F811
    body = mi(ran)
    cases = queue(ran)  # largest absolute impact first
    assert [r["case_id"] for r in body["top_open"]] == [c["case_id"] for c in cases[:5]]
    assert all(r["security_name"] or not r["security_id"] for r in body["top_open"])
    impacts = [abs(r["nav_impact"]) for r in body["top_open"]]
    assert impacts == sorted(impacts, reverse=True)


def test_mi_matches_the_engine_across_days(ran, make_client, factory, day_files, db_session):  # noqa: F811
    three_days(ran, make_client, factory, day_files)
    fund = db_session.query(Fund).one()
    history = ledger_history(db_session, fund, DAY3)
    assert list(history) == [str(DAY1), str(DAY2), str(DAY3)]
    engine = build_mi(str(DAY3), history[str(DAY3)], history)

    body = mi(make_client("viewer1"), DAY3)
    assert body["run_days"] == 3
    assert [t["as_of"] for t in body["trend"]] == [str(DAY1), str(DAY2), str(DAY3)]
    assert [t["avg_days_to_resolve"] for t in body["trend"]] == [t.avg_days_to_resolve for t in engine.trend]
    assert [t["open_cases"] for t in body["trend"]] == [len(queue(ran, d)) for d in (DAY1, DAY2, DAY3)]
    assert body["time_to_resolve"]["all"]["avg_days"] == engine.avg_days_to_resolve
    assert {r["cause"]: (r["cleared"], r["avg_days"]) for r in body["time_to_resolve"]["rows"]} == \
        engine.resolve_by_cause
    assert [r["case_id"] for r in body["top_open"]] == [c.case_id for c in engine.top_cases]
    assert [r["case_id"] for r in body["sla_breaches"]] == [c.case_id for c in engine.sla_breaches]
    cells = {(r["cause"], c["bucket"]): c for r in body["by_cause_age"]["rows"] for c in r["cells"] if c["count"]}
    assert {k: v["count"] for k, v in cells.items()} == engine.by_cause_age
    assert {k: v["net"] for k, v in cells.items()} == engine.impact_by_cause_age

    # Cases cleared on day 2 still count towards the time to resolve on day 3.
    cleared = sum(len(ran.get(f"{DAYS_URL}/{d}/overview").json()["cleared_today"]) for d in (DAY2, DAY3))
    assert cleared > 0 and body["time_to_resolve"]["all"]["cleared"] == cleared
    for t in body["trend"]:
        assert t["open_gross_impact"] >= abs(t["open_nav_impact"])

    # The overview's trend is the same series (without the gross figure).
    overview_trend = ran.get(f"{DAYS_URL}/{DAY3}/overview").json()["trend"]
    assert overview_trend == [{k: v for k, v in t.items() if k != "open_gross_impact"} for t in body["trend"]]
    # An earlier day's MI stops at that day.
    assert [t["as_of"] for t in mi(ran, DAY2)["trend"]] == [str(DAY1), str(DAY2)]


# --------------------------------------------------------------------------- exports


def test_mi_csv_export_is_tidy_and_audited(ran, make_client, factory, day_files, db_session):  # noqa: F811
    sign_off(ran, make_client, DAY1)
    run_day(ran, factory, day_files[1], as_of=DAY2)
    viewer = make_client("viewer1")
    response = viewer.get(f"{DAYS_URL}/{DAY2}/exports/mi.csv")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == f'attachment; filename="mi_{FUND_CODE}_{DAY2}.csv"'
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))
    assert list(rows[0]) == MI_COLUMNS
    assert {r["as_of"] for r in rows} == {str(DAY1), str(DAY2)}
    keyed = {(r["as_of"], r["metric"], r["cause"], r["age_bucket"]): r["value"] for r in rows}
    body = mi(viewer, DAY2)
    assert keyed[(str(DAY2), "open_cases", "ALL", "ALL")] == str(body["trend"][-1]["open_cases"])

    [entry] = exports(db_session)
    assert (entry["actor"], entry["role"]) == ("viewer1", "viewer")
    assert entry["payload"] == {
        "as_of": str(DAY2), "export": "mi_csv", "filename": f"mi_{FUND_CODE}_{DAY2}.csv",
        "bytes": len(response.content), "sha256": hashlib.sha256(response.content).hexdigest(), "run_days": 2,
    }


def test_report_export_is_the_engine_workbook_and_audited(ran, make_client, db_session):  # noqa: F811
    sign_off(ran, make_client, DAY1)
    response = ran.get(f"{DAYS_URL}/{DAY1}/exports/report.xlsx")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert response.headers["content-disposition"] == f'attachment; filename="exceptions_{FUND_CODE}_{DAY1}.xlsx"'
    wb = load_workbook(io.BytesIO(response.content))
    assert wb.sheetnames == ["Summary", "Exceptions", "Breaks", "Cash matching", "NAV checks", "MI"]

    summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(min_row=3, values_only=True) if row[0]}
    assert summary["Signed off by"] == "approver2"
    assert summary["Cases"] == len(queue(ran))
    exceptions = [row[0] for row in wb["Exceptions"].iter_rows(min_row=2, values_only=True)]
    assert exceptions == [c["case_id"] for c in queue(ran)]
    checks = [row[0] for row in wb["NAV checks"].iter_rows(min_row=2, values_only=True)]
    assert "Material cases approved" in checks and "NAV release" not in checks
    breaks = ran.get(f"{DAYS_URL}/{DAY1}/overview").json()["accounted"]["breaks_found"]
    assert wb["Breaks"].max_row - 1 == breaks
    assert wb["MI"]["A1"].value == f"Management information, {DAY1}"

    [entry] = exports(db_session)
    assert (entry["actor"], entry["action"]) == ("analyst1", "EXPORT_DOWNLOADED")
    assert entry["payload"]["export"] == "exception_report"
    assert entry["payload"]["sha256"] == hashlib.sha256(response.content).hexdigest()
    assert entry["payload"]["as_of"] == str(DAY1) and entry["payload"]["run_days"] == 1


def test_report_before_sign_off_says_not_signed_off(ran):  # noqa: F811
    response = ran.get(f"{DAYS_URL}/{DAY1}/exports/report.xlsx")
    assert response.status_code == 200
    wb = load_workbook(io.BytesIO(response.content))
    summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(min_row=3, values_only=True) if row[0]}
    assert summary["Signed off by"] == "not signed off"
    assert summary["Review status"].startswith("PENDING")
