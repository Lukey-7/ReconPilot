"""Multi-day lifecycle: carried items, ageing, escalation, SLAs and auto-clearing."""

from datetime import date, timedelta

from conftest import AS_OF, cash, make_day, trade

from reconpilot.audit import AuditLog
from reconpilot.ledger import LifecycleSettings, age_bucket, business_days_between, days_to_resolve
from reconpilot.matching import carry_forward
from reconpilot.models import Category
from reconpilot.pipeline import run_day

FRI = AS_OF  # 2026-11-13 is a Friday
MON = FRI + timedelta(days=3)


def next_day(day_data, as_of, previous):
    """Carry the previous result's open items into a new day."""
    day_data.as_of = as_of
    day_data.carried_book_items, day_data.carried_custodian_lines = carry_forward(previous.recon)
    return day_data


def test_business_days_and_buckets():
    assert business_days_between(FRI, MON) == 1
    assert business_days_between(FRI, FRI) == 0
    assert business_days_between(date(2026, 11, 2), date(2026, 11, 13)) == 9
    assert [age_bucket(n) for n in (0, 1, 2, 5, 6)] == ["0-1", "0-1", "2-5", "2-5", ">5"]


def test_late_settlement_clears_next_day_and_resolves_as_timing(tmp_path):
    audit = AuditLog(tmp_path / "a.jsonl")
    t = trade("T1", "A", qty=200, price=50)
    # Friday: book settles T1, custodian shows nothing (no pending line), so rules say MISSING_TRADE.
    fri = make_day({"A": "USD"}, {"A": (1200, 50)}, [t], holdings={"A": (1000, 50)})
    day1 = run_day(fri, audit=audit)
    case = day1.open_cases[0]
    assert case.category is Category.MISSING_TRADE
    assert case.first_seen == str(FRI)

    # Monday: custodian settles T1; book has no new trades.
    mon = make_day({"A": "USD"}, {"A": (1200, 50)}, holdings={"A": (1200, 50)},
                   cash_lines=[cash("C9", "A", "T1", t.cash_amount, value_date=MON)])
    day2 = run_day(next_day(mon, MON, day1), day1.open_cases, audit=audit)
    assert day2.recon.breaks == []
    assert day2.open_cases == []
    cleared = day2.cleared[0]
    assert cleared.case_id == case.case_id
    assert cleared.cleared_on == str(MON)
    assert cleared.resolved_category is Category.TIMING
    assert days_to_resolve(cleared) == 1
    assert "CASE_AUTO_CLEARED" in [e["action"] for e in audit.entries()]


def test_unbooked_dividend_persists_and_ages_until_booked():
    div = cash("C1", "A", "DV1", 450.0, "CASH DIVIDEND")
    day1 = run_day(make_day({"A": "USD"}, {"A": (1000, 50)}, cash_lines=[div]))
    prior = day1.open_cases

    # Next three business days: the custodian line is not repeated, but stays open.
    result = day1
    as_of = FRI
    for _ in range(3):
        as_of += timedelta(days=3 if as_of.weekday() == 4 else 1)
        result = run_day(next_day(make_day({"A": "USD"}, {"A": (1000, 50)}), as_of, result), prior)
        prior = result.open_cases
    case = prior[0]
    assert case.category is Category.DIVIDEND
    assert (case.age_days, case.age_bucket) == (3, "2-5")
    assert case.case_id == day1.open_cases[0].case_id

    # The book accrues it: the carried custodian line now matches by reference.
    from reconpilot.models import BookCashEntry

    as_of += timedelta(days=1)
    booked = make_day({"A": "USD"}, {"A": (1000, 50)})
    booked.book_cash = [BookCashEntry("DV1", as_of, "A", "Dividend accrual", 450.0)]
    final = run_day(next_day(booked, as_of, result), prior)
    assert final.open_cases == []
    assert final.cleared[0].resolved_category is Category.DIVIDEND


def test_escalation_and_sla_breach_are_audited_once(tmp_path):
    audit = AuditLog(tmp_path / "a.jsonl")
    settings = LifecycleSettings(materiality_bp=1000, escalate_after_days=2, sla_days_other=1)
    day = make_day({"A": "USD"}, {"A": (1000, 100)}, holdings={"A": (1000, 103)})
    result = run_day(day, settings=settings, audit=audit)
    as_of = FRI
    for _ in range(4):
        as_of += timedelta(days=3 if as_of.weekday() == 4 else 1)
        nxt = make_day({"A": "USD"}, {"A": (1000, 100)}, holdings={"A": (1000, 103)})
        result = run_day(next_day(nxt, as_of, result), result.open_cases, settings, audit=audit)
    case = result.open_cases[0]
    assert case.age_days == 4
    assert case.escalated and case.escalation_reason == "aged: open 3 business days"
    assert case.sla_breached
    actions = [e["action"] for e in audit.entries()]
    assert actions.count("CASE_ESCALATED") == 1
    assert actions.count("SLA_BREACHED") == 1


def test_material_cases_escalate_immediately():
    day = make_day({"A": "USD"}, {"A": (100_000, 100)}, holdings={"A": (100_000, 98)})
    case = run_day(day).open_cases[0]
    assert case.material and case.escalated
    assert case.escalation_reason.startswith("material")
    assert case.sla_days == LifecycleSettings().sla_days_material


def test_review_decision_carries_over_while_cause_is_unchanged():
    day1 = run_day(make_day({"A": "USD"}, {"A": (1000, 100)}, holdings={"A": (1000, 103)}))
    c = day1.open_cases[0]
    c.status, c.reviewed_by, c.reviewed_role = "APPROVED", "priya", "analyst"
    nxt = make_day({"A": "USD"}, {"A": (1000, 100)}, holdings={"A": (1000, 103)})
    day2 = run_day(next_day(nxt, MON, day1), day1.open_cases)
    assert day2.open_cases[0].status == "APPROVED"
    assert day2.open_cases[0].reviewed_by == "priya"


def test_cash_amount_pair_stays_open_and_clears_with_adjustment():
    from reconpilot.models import BookCashEntry

    t = trade("T1", "B", qty=1000, price=20, ccy="EUR")
    off = round(t.cash_amount * 1.01, 2)
    day1 = run_day(make_day({"B": "EUR"}, {"B": (5000, 20)}, [t], cash_lines=[cash("C1", "B", "T1", off)]))
    assert day1.open_cases[0].category is Category.FX_DIFFERENCE

    fix = make_day({"B": "EUR"}, {"B": (5000, 20)})
    fix.book_cash = [BookCashEntry("ADJ-T1", MON, "B", "FX adjustment", round(off - t.cash_amount, 2))]
    day2 = run_day(next_day(fix, MON, day1), day1.open_cases)
    assert day2.open_cases == []
    assert [m.kind for m in day2.recon.matches] == ["MANY_TO_ONE"]
