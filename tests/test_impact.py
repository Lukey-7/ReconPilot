import pytest
from conftest import cash, make_day, trade

from reconpilot.audit import AuditLog
from reconpilot.impact import apply_impacts, blocking_cases, case_impact, release_check
from reconpilot.matching import reconcile
from reconpilot.nav import compute_nav
from reconpilot.review import ReviewError, ReviewSession
from reconpilot.triage import triage


def cases_for(day, materiality_bp=1.0):
    recon = reconcile(day)
    cases = triage(day, recon)
    return day, recon, apply_impacts(day, recon, cases, compute_nav(day), materiality_bp)


def by_security(cases):
    return {c.security_id: c for c in cases}


def test_price_mismatch_impact_is_quantity_times_price_difference():
    day, recon, cases = cases_for(make_day({"A": "USD"}, {"A": (1000, 100)}, holdings={"A": (1000, 103)}))
    assert cases[0].nav_impact == 3000.0
    nav = compute_nav(day).nav
    assert cases[0].nav_impact_bp == pytest.approx(3000 / nav * 10_000, abs=1e-4)


def test_dividend_impact_is_the_credit():
    day = make_day({"A": "USD"}, {"A": (1000, 50)}, cash_lines=[cash("C1", "A", "DV1", 450.0, "DIV")])
    _, _, cases = cases_for(day)
    assert cases[0].nav_impact == 450.0
    assert cases[0].gross_exposure == 450.0


def test_missing_trade_nets_position_against_cash():
    # Custodian bought 200 at 50.05 (cash -10,010); market price 50, so NAV falls by 10.
    day = make_day({"A": "USD"}, {"A": (1000, 50)}, holdings={"A": (1200, 50)},
                   cash_lines=[cash("C1", "A", "CUS1", -10_010.0)])
    _, recon, cases = cases_for(day)
    impact, gross = case_impact(day, recon, cases[0])
    assert impact == -10.0
    assert gross == 20_010.0


def test_split_has_no_nav_impact():
    _, _, cases = cases_for(make_day({"A": "USD"}, {"A": (1000, 90)}, holdings={"A": (3000, 30)}))
    assert cases[0].nav_impact == 0.0
    assert not cases[0].material


def test_cases_sorted_by_absolute_impact_and_flagged_material():
    day = make_day(
        {"A": "USD", "B": "USD", "C": "USD"},
        {"A": (1000, 100), "B": (100_000, 100), "C": (1000, 50)},
        holdings={"A": (1000, 101), "B": (100_000, 99), "C": (1000, 50)},
        cash_lines=[cash("C1", "C", "DV1", 20.0, "DIV")],
    )
    _, _, cases = cases_for(day, materiality_bp=10)
    assert [c.security_id for c in cases] == ["B", "A", "C"]
    assert cases[0].nav_impact == -100_000.0
    assert [c.material for c in cases] == [True, False, False]


def test_release_blocked_until_material_cases_approved(tmp_path):
    day = make_day({"A": "USD", "B": "USD"}, {"A": (100_000, 100), "B": (10, 10)},
                   holdings={"A": (100_000, 99), "B": (10, 10.5)})
    _, _, cases = cases_for(day)
    material = [c for c in cases if c.material]
    assert len(material) == 1
    assert release_check(cases).status == "FAIL"
    assert blocking_cases(cases) == material

    audit = AuditLog(tmp_path / "a.jsonl")
    analyst = ReviewSession(cases, audit, "priya", "analyst")
    for c in cases:
        analyst.approve(c.case_id) if not c.material else analyst.reject(c.case_id, "price source wrong")
    with pytest.raises(ReviewError, match="NAV release blocked"):
        ReviewSession(cases, audit, "tom", "approver").sign_off()

    analyst.approve(material[0].case_id)
    assert release_check(cases).status == "PASS"
    ReviewSession(cases, audit, "tom", "approver").sign_off()


def test_pending_queue_is_ordered_by_impact(tmp_path):
    day = make_day({"A": "USD", "B": "USD"}, {"A": (10, 100), "B": (5000, 100)},
                   holdings={"A": (10, 102), "B": (5000, 102)})
    _, _, cases = cases_for(day)
    session = ReviewSession(list(reversed(cases)), AuditLog(tmp_path / "a.jsonl"), "priya", "analyst")
    assert [c.security_id for c in session.pending()] == ["B", "A"]


def test_timing_break_has_small_net_impact():
    t = trade("T1", "A", qty=200, price=50, fees=5.0)
    day = make_day({"A": "USD"}, {"A": (1200, 50)}, [t], holdings={"A": (1000, 50)})
    _, _, cases = cases_for(day)
    # Book paid 10,005 for 200 units now worth 10,000: correcting to the custodian adds back 5.
    assert cases[0].nav_impact == 5.0
