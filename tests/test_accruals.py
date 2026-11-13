from datetime import date

import pytest
from conftest import make_day

from reconpilot.generator import GeneratorConfig, generate_day
from reconpilot.matching import reconcile
from reconpilot.models import PLANTABLE, Accrual
from reconpilot.nav import accrual_check, accrual_days, compute_nav, expected_accruals, run_checks

FRIDAY = date(2026, 11, 13)
MONDAY = date(2026, 11, 16)


def fund(as_of=FRIDAY):
    day = make_day({"A": "USD"}, {"A": (1000, 50)})
    day.as_of = as_of
    day.prior_nav_per_share = 10.0  # 100,000 shares -> prior NAV 1,000,000
    day.management_fee_rate = 0.0073  # chosen so one day is exactly 20.00
    day.daily_expense_budget = 5.0
    return day


def test_accrual_days_cover_weekends():
    assert accrual_days(FRIDAY) == 1
    assert accrual_days(MONDAY) == 3


def test_expected_accruals():
    assert expected_accruals(fund()) == {"MANAGEMENT_FEE": 20.0, "EXPENSES": 5.0}
    assert expected_accruals(fund(MONDAY)) == {"MANAGEMENT_FEE": 60.0, "EXPENSES": 15.0}


def test_accruals_reduce_nav():
    day = fund()
    day.accrued_expenses = 100.0
    day.accruals = [Accrual(FRIDAY, "MANAGEMENT_FEE", 20.0), Accrual(FRIDAY, "EXPENSES", 5.0)]
    nav = compute_nav(day)
    assert nav.liabilities == 125.0
    assert nav.nav == 1_050_000.0 - 125.0
    assert accrual_check(day).status == "PASS"


def test_missed_fee_accrual_fails():
    day = fund()
    day.accruals = [Accrual(FRIDAY, "EXPENSES", 5.0)]
    check = accrual_check(day)
    assert check.status == "FAIL"
    assert "management fee not accrued (expected 20.00)" in check.detail


def test_wrong_accrual_warns_and_weekend_is_checked():
    day = fund(MONDAY)
    # Only one day's fee booked on a Monday.
    day.accruals = [Accrual(MONDAY, "MANAGEMENT_FEE", 20.0), Accrual(MONDAY, "EXPENSES", 15.0)]
    check = accrual_check(day)
    assert check.status == "WARN"
    assert "accrued 20.00, expected 60.00" in check.detail


def test_no_accruals_configured_passes():
    day = make_day({"A": "USD"}, {"A": (1000, 50)})
    assert accrual_check(day).status == "PASS"


@pytest.mark.parametrize("rate, status", [(0.0, "PASS"), (1.0, "FAIL")])
def test_generator_books_or_misses_accruals(rate, status):
    day, _ = generate_day(FRIDAY, PLANTABLE, seed=2, config=GeneratorConfig(missed_accrual_rate=rate))
    checks = {c.name: c for c in run_checks(day, compute_nav(day), reconcile(day))}
    assert checks["Accruals"].status == status
    assert day.accrued_today > 0
