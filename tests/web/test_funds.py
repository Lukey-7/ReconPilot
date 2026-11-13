"""Funds, per-fund settings and the business calendar."""

from __future__ import annotations

from datetime import date

import pytest

from reconpilot.ledger import LifecycleSettings
from reconpilot_web import cli
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.funds import (
    DEFAULT_FUND_SETTINGS,
    fund_check_settings,
    fund_lifecycle,
    is_business_day,
    previous_business_day,
)
from reconpilot_web.models import BusinessDay, Fund

from .conftest import FUND_CODE


def _fund(start: date, holidays: list[date] | None = None, settings: dict | None = None) -> Fund:
    return Fund(code="X", name="X", start_date=start, non_business_dates=holidays or [], settings=settings or {})


# --------------------------------------------------------------------------- calendar


def test_previous_business_day_skips_weekend_and_holidays():
    fund = _fund(date(2026, 11, 2), holidays=[date(2026, 11, 13)])
    # Monday 16th: Sunday and Saturday are weekend, Friday 13th a holiday.
    assert previous_business_day(fund, date(2026, 11, 16)) == date(2026, 11, 12)
    assert previous_business_day(fund, date(2026, 11, 12)) == date(2026, 11, 11)
    assert previous_business_day(_fund(date(2026, 11, 2)), date(2026, 11, 16)) == date(2026, 11, 13)


def test_start_date_has_no_previous_day():
    fund = _fund(date(2026, 11, 11))
    assert previous_business_day(fund, date(2026, 11, 11)) is None
    assert previous_business_day(fund, date(2026, 11, 10)) is None
    assert previous_business_day(fund, date(2026, 11, 12)) == date(2026, 11, 11)


def test_is_business_day():
    fund = _fund(date(2026, 11, 2), holidays=[date(2026, 11, 13)])
    assert is_business_day(fund, date(2026, 11, 12))
    assert not is_business_day(fund, date(2026, 11, 13))  # holiday
    assert not is_business_day(fund, date(2026, 11, 14))  # Saturday
    assert not is_business_day(fund, date(2026, 11, 15))  # Sunday


# --------------------------------------------------------------------------- settings


def test_defaults_are_the_engines():
    engine = LifecycleSettings()
    assert DEFAULT_FUND_SETTINGS == {
        "materiality_bp": 1.0,
        "escalate_after_days": 5,
        "sla_days_material": 2,
        "sla_days_other": 5,
        "ai_enabled": False,
        "check_settings": {},
    }
    assert fund_lifecycle(_fund(date(2026, 11, 2))) == engine
    assert fund_check_settings(_fund(date(2026, 11, 2))) == {}


def test_fund_settings_reach_lifecycle_and_checks():
    fund = _fund(date(2026, 11, 2), settings={
        "materiality_bp": 2.5, "sla_days_material": 1,
        "check_settings": {"price_move_limits": {"EQUITY": 0.02, "BOND": 0.01}},
    })
    assert fund_lifecycle(fund) == LifecycleSettings(materiality_bp=2.5, sla_days_material=1)
    assert fund_check_settings(fund) == {"price_move_limits": {"EQUITY": 0.02, "BOND": 0.01}}


def test_create_fund_audited_and_validated(make_fund, db_session):
    fund = make_fund(non_business_dates=[date(2026, 11, 26)])
    entries = DbAuditLog(db_session).entries()
    assert [e["action"] for e in entries] == ["FUND_CREATED"]
    assert entries[0]["payload"]["code"] == FUND_CODE
    assert entries[0]["payload"]["non_business_dates"] == ["2026-11-26"]
    assert db_session.get(Fund, fund.id).settings == DEFAULT_FUND_SETTINGS

    with pytest.raises(ValueError, match="already exists"):
        make_fund()
    with pytest.raises(ValueError, match="not a business day"):
        make_fund(code="SAT", start_date=date(2026, 11, 14))
    with pytest.raises(ValueError, match="Fund code"):
        make_fund(code="bad code")
    with pytest.raises(ValueError, match="Unknown check settings"):
        make_fund(code="F2", settings={"check_settings": {"nonsense": 1}})
    with pytest.raises(ValueError, match="Base currency"):
        make_fund(code="F3", base_currency="EUR")


def test_cli_create_fund(clean_db, pg_uri, pg_dir, db_session, capsys, monkeypatch):
    for name, value in {"RP_DATABASE_URL": pg_uri, "RP_MODE": "real", "RP_DATA_DIR": str(pg_dir)}.items():
        monkeypatch.setenv(name, value)
    assert cli.main(["create-fund", "--code", "gef2", "--name", "Global Equity 2", "--start-date", "2026-11-09",
                     "--non-business-date", "2026-11-26"]) == 0
    assert "Created fund GEF2" in capsys.readouterr().out
    fund = db_session.query(Fund).filter_by(code="GEF2").one()
    assert fund.start_date == date(2026, 11, 9) and fund.non_business_dates == [date(2026, 11, 26)]
    assert cli.main(["create-fund", "--code", "GEF2", "--name", "Again", "--start-date", "2026-11-09"]) == 1
    assert "already exists" in capsys.readouterr().err


# --------------------------------------------------------------------------- routes


def test_list_funds_requires_sign_in(client, fund):
    assert client.get("/api/funds").status_code == 401
    assert client.get(f"/api/funds/{FUND_CODE}").status_code == 401


def test_viewer_can_list_funds(make_client, users, fund, db_session):
    viewer = make_client("viewer1")
    response = viewer.get("/api/funds")
    assert response.status_code == 200
    assert response.json() == [{
        "code": FUND_CODE, "name": "Global Equity Fund", "base_currency": "USD", "start_date": "2026-11-09",
        "latest_day": None, "latest_status": None,
    }]

    db_session.add(BusinessDay(fund_id=fund.id, as_of=date(2026, 11, 9), status="signed_off"))
    db_session.add(BusinessDay(fund_id=fund.id, as_of=date(2026, 11, 10), status="validated"))
    db_session.commit()
    listed = viewer.get("/api/funds").json()[0]
    assert (listed["latest_day"], listed["latest_status"]) == ("2026-11-10", "validated")

    detail = viewer.get(f"/api/funds/{FUND_CODE.lower()}")
    assert detail.status_code == 200
    assert detail.json()["settings"] == DEFAULT_FUND_SETTINGS
    assert detail.json()["non_business_dates"] == []
    assert viewer.get("/api/funds/NOPE").status_code == 404
