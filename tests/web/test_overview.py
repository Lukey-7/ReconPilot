"""The fund's day listing and the morning overview."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from reconpilot_web.models import BreakRow, BusinessDay

from .conftest import FUND_CODE, FUND_START
from .test_release import (
    DAY1,
    DAY2,
    MATERIALITY_BP,
    decide,
    decide_all,
    factory,  # noqa: F401  (fixture)
    queue,
    ran,  # noqa: F401  (fixture)
    release,
    run_day,
)
from .test_upload import upload

DAYS_URL = f"/api/funds/{FUND_CODE}/days"


def overview(client, as_of: date = DAY1) -> dict:
    response = client.get(f"{DAYS_URL}/{as_of}/overview")
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- day listing


def test_days_list_for_a_new_fund_offers_the_start_date(make_client, users, fund):
    body = make_client("viewer1").get(DAYS_URL).json()
    assert body == {"fund": FUND_CODE, "start_date": str(FUND_START), "latest_day": None,
                    "next_day": str(FUND_START), "days": []}


def test_days_list_newest_first_with_status(ran, make_client, factory, day_files):  # noqa: F811
    body = ran.get(DAYS_URL).json()
    assert body["latest_day"] == str(DAY1) and body["next_day"] is None  # day 1 is not signed off yet
    [day] = body["days"]
    assert day["as_of"] == str(DAY1) and day["status"] == "ready"
    assert day["nav_per_share"] > 0 and day["open_cases"] == len(queue(ran)) and day["run_at"]
    assert day["signed_off_by"] is None

    decide_all(ran, make_client("approver1"))
    assert make_client("approver2").post(f"{DAYS_URL}/{DAY1}/signoff").status_code == 200
    body = ran.get(DAYS_URL).json()
    assert body["next_day"] == str(DAY2)
    assert body["days"][0]["status"] == "signed_off" and body["days"][0]["signed_off_by"] == "approver2"

    assert upload(ran, day_files[1], as_of=DAY2).json()["status"] == "validated"
    body = ran.get(DAYS_URL).json()
    assert [d["as_of"] for d in body["days"]] == [str(DAY2), str(DAY1)]
    assert body["days"][0]["status"] == "validated" and body["days"][0]["nav_per_share"] is None
    assert body["days"][0]["open_cases"] is None and body["next_day"] is None


def test_next_day_skips_weekends_and_holidays(make_client, users, make_fund, factory):  # noqa: F811
    friday = date(2026, 11, 13)
    fund = make_fund(start_date=friday, non_business_dates=[date(2026, 11, 16)])
    # Only the listing is under test, so the Friday is put straight into the signed-off state.
    with factory() as session, session.begin():
        session.add(BusinessDay(fund_id=fund.id, as_of=friday, status="signed_off"))
    assert make_client("analyst1").get(DAYS_URL).json()["next_day"] == "2026-11-17"  # Monday is a holiday


def test_days_list_requires_sign_in(client, fund):
    assert client.get(DAYS_URL).status_code == 401


# --------------------------------------------------------------------------- overview


def test_overview_requires_sign_in_and_a_day(client, make_client, users, fund):
    assert client.get(f"{DAYS_URL}/{DAY1}/overview").status_code == 401
    analyst = make_client("analyst1")
    response = analyst.get(f"{DAYS_URL}/{DAY1}/overview")
    assert response.status_code == 404
    assert analyst.get(f"{DAYS_URL}/not-a-date/overview").status_code == 422


def test_overview_before_the_run(make_client, users, fund, day_files):
    analyst = make_client("analyst1")
    assert upload(analyst, day_files[0]).json()["status"] == "validated"
    body = overview(analyst)
    assert body["has_run"] is False and body["day_status"] == "validated"
    assert body["release"]["ready"] is False
    assert [r["code"] for r in body["release"]["reasons"]] == ["NOT_RUN"]
    for key in ("nav", "run", "accounted", "impact"):
        assert body[key] is None
    assert body["sla_breaches"] == body["escalations"] == body["cleared_today"] == body["trend"] == []
    assert [(b["bucket"], b["count"]) for b in body["ageing"]] == [("0-1", 0), ("2-5", 0), (">5", 0)]
    assert body["fund"] == {"code": FUND_CODE, "name": "Global Equity Fund", "base_currency": "USD",
                            "materiality_bp": 1.0}


def test_every_break_accounted_for(ran, make_client, db_session):  # noqa: F811
    body = overview(ran)
    acc = body["accounted"]
    day_id = db_session.execute(select(BusinessDay.id).where(BusinessDay.as_of == DAY1)).scalar_one()
    found = db_session.execute(select(func.count()).where(BreakRow.business_day_id == day_id)).scalar_one()
    in_cases = db_session.execute(
        select(func.count()).where(BreakRow.business_day_id == day_id, BreakRow.case_id.is_not(None))
    ).scalar_one()
    assert found > 0
    assert acc["breaks_found"] == found == body["run"]["breaks"]
    assert acc["breaks_in_cases"] == in_cases
    assert acc["breaks_in_cases"] + acc["breaks_not_in_case"] == acc["breaks_found"]
    assert acc["open_cases"] == len(queue(ran)) and acc["pending"] == acc["open_cases"] and acc["decided"] == 0

    first, second = queue(ran)[-2:]  # the smallest cases: not escalated at this threshold
    decide(ran, first)
    decide(ran, second, "reject", note="Custodian confirmed its figure.")
    acc = overview(ran)["accounted"]
    assert (acc["approved"], acc["rejected"], acc["reclassified"]) == (1, 1, 0)
    assert acc["decided"] == 2 and acc["decided"] + acc["pending"] == acc["open_cases"]


def test_open_breaks_by_impact_with_gross_and_net(ran):  # noqa: F811
    body = overview(ran)
    impact = body["impact"]
    rows = impact["cases"]
    assert [r["case_id"] for r in rows] == [c["case_id"] for c in queue(ran)]  # largest absolute impact first
    assert impact["net"] == round(sum(r["nav_impact"] for r in rows), 2)
    assert impact["gross"] == round(sum(abs(r["nav_impact"]) for r in rows), 2)
    assert impact["gross"] >= abs(impact["net"])
    assert impact["gross_exposure"] == round(sum(r["gross_exposure"] for r in rows), 2)
    assert impact["material"] == sum(1 for r in rows if r["material"]) >= 1
    assert body["fund"]["materiality_bp"] == MATERIALITY_BP
    for key in ("reviewed_by", "reviewed_role", "sla_days", "escalation_reason", "first_seen", "version"):
        assert key in rows[0]


def test_ageing_buckets_cover_every_open_case(ran):  # noqa: F811
    body = overview(ran)
    assert [b["bucket"] for b in body["ageing"]] == ["0-1", "2-5", ">5"]
    assert sum(b["count"] for b in body["ageing"]) == body["accounted"]["open_cases"]
    assert round(sum(b["net"] for b in body["ageing"]), 2) == body["impact"]["net"]


def test_release_and_checks_match_the_release_route(ran, make_client):  # noqa: F811
    for client in (ran, make_client("viewer1")):
        body, rel = overview(client), release(client)
        assert body["release"] == {"ready": rel["ready"], "reasons": rel["reasons"]}
        assert body["checks"] == rel["checks"]
    names = [c["name"] for c in overview(ran)["checks"]]
    assert "Material cases approved" in names and "NAV release" not in names


def test_sla_breaches_and_escalations(ran):  # noqa: F811
    body = overview(ran)
    rows = body["impact"]["cases"]
    assert body["escalations"] == [r for r in rows if r["escalated"]]
    assert body["escalations"] and all(r["escalation_reason"] for r in body["escalations"])
    assert body["sla_breaches"] == [r for r in rows if r["sla_breached"]]


def test_second_day_cleared_today_and_trend(ran, make_client, factory, day_files):  # noqa: F811
    decide_all(ran, make_client("approver1"))
    assert make_client("approver2").post(f"{DAYS_URL}/{DAY1}/signoff").status_code == 200
    day1 = overview(ran)
    assert day1["signed_off_by"] == "approver2" and day1["release"]["ready"] is True
    assert day1["accounted"]["pending"] == 0

    run_day(ran, factory, day_files[1], as_of=DAY2)
    body = overview(ran, DAY2)
    summary = ran.get(f"{DAYS_URL}/{DAY2}").json()["summary"]
    assert sorted(c["case_id"] for c in body["cleared_today"]) == sorted(summary["cleared_today"])
    assert body["cleared_today"], "the generated second day clears at least one case"
    assert all(c["clear_reason"] and c["age_days"] >= 1 for c in body["cleared_today"])

    trend = body["trend"]
    assert [t["as_of"] for t in trend] == [str(DAY1), str(DAY2)]
    assert trend[0]["open_cases"] == len(queue(ran, DAY1))
    assert trend[1]["open_cases"] == len(queue(ran, DAY2)) == body["accounted"]["open_cases"]
    assert trend[1]["cleared_cases"] == len(body["cleared_today"])
    assert trend[1]["new_cases"] == summary["new_cases"]
    # Day 1's view of the trend stops at day 1.
    assert [t["as_of"] for t in overview(ran, DAY1)["trend"]] == [str(DAY1)]
