import json

import pytest
from conftest import cash, make_day

from reconpilot.audit import AuditLog
from reconpilot.matching import reconcile
from reconpilot.models import Category
from reconpilot.nav import compute_nav, run_checks
from reconpilot.review import PermissionDenied, ReviewError, ReviewSession
from reconpilot.triage import triage


def sample_cases():
    day = make_day({"A": "USD", "B": "USD"}, {"A": (1000, 90), "B": (100, 10)},
                   holdings={"A": (3000, 30), "B": (100, 10.5)})
    return triage(day, reconcile(day))


def test_audit_chain_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append("u", "analyst", "EVENT", {"i": i})
    assert log.verify() == (True, None)

    lines = log.path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["payload"]["i"] = 99
    lines[1] = json.dumps(entry, sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n")
    assert log.verify() == (False, 2)


def test_audit_chain_detects_deleted_entry(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append("u", "analyst", "EVENT", {"i": i})
    lines = log.path.read_text().splitlines()
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert log.verify()[0] is False


def test_viewer_cannot_decide(tmp_path):
    session = ReviewSession(sample_cases(), AuditLog(tmp_path / "a.jsonl"), "val", "viewer")
    with pytest.raises(PermissionDenied):
        session.approve("EX-20261113-001")
    assert session.audit.entries()[-1]["action"] == "PERMISSION_DENIED"


def test_review_decisions_are_logged(tmp_path):
    session = ReviewSession(sample_cases(), AuditLog(tmp_path / "a.jsonl"), "priya", "analyst")
    session.approve("EX-20261113-001")
    session.reclassify("EX-20261113-002", Category.UNKNOWN, "price source under review")
    actions = [e["action"] for e in session.audit.entries()]
    assert actions == ["CASE_APPROVED", "CASE_RECLASSIFIED"]
    assert session.cases["EX-20261113-002"].final_category is Category.UNKNOWN


def test_rejection_requires_a_note(tmp_path):
    session = ReviewSession(sample_cases(), AuditLog(tmp_path / "a.jsonl"), "priya", "analyst")
    with pytest.raises(ReviewError):
        session.reject("EX-20261113-001")


def test_sign_off_needs_all_reviewed_and_a_second_person(tmp_path):
    cases = sample_cases()
    audit = AuditLog(tmp_path / "a.jsonl")
    approver = ReviewSession(cases, audit, "tom", "approver")
    with pytest.raises(ReviewError):
        approver.sign_off()

    approver.approve("EX-20261113-001")
    ReviewSession(cases, audit, "priya", "analyst").approve("EX-20261113-002")
    with pytest.raises(PermissionDenied):  # tom reviewed a case himself
        approver.sign_off()

    ReviewSession(cases, audit, "priya", "analyst").approve("EX-20261113-001")
    with pytest.raises(PermissionDenied):  # analysts cannot sign off
        ReviewSession(cases, audit, "priya", "analyst").sign_off()
    assert ReviewSession(cases, audit, "tom", "approver").sign_off()["action"] == "DAY_SIGNED_OFF"
    assert audit.verify()[0]


def test_nav_checks_flag_stale_price_and_cash_gap():
    day = make_day({"A": "USD"}, {"A": (1000, 50)}, cash_lines=[cash("C1", "A", "DV1", 450.0, "DIV")])
    day.book_positions["A"].price_date = day.as_of.replace(day=6)
    recon = reconcile(day)
    nav = compute_nav(day)
    checks = {c.name: c for c in run_checks(day, nav, recon)}
    assert checks["Stale prices"].status == "WARN"
    # The gap is fully explained by the open dividend break, so it warns rather than fails.
    assert checks["Cash tie-out"].status == "WARN"
    assert "450.00" in checks["Cash tie-out"].detail


def test_nav_movement_threshold():
    day = make_day({"A": "USD"}, {"A": (1000, 50)})
    day.prior_nav_per_share = 10.4
    nav = compute_nav(day)
    assert nav.nav == 1_050_000.0
    assert nav.nav_per_share == 10.5
    checks = {c.name: c for c in run_checks(day, nav, reconcile(day))}
    assert checks["NAV movement"].status == "PASS"  # +0.96%, under the 2% threshold


def test_nav_movement_warns_on_large_move():
    day = make_day({"A": "USD"}, {"A": (1000, 50)})
    day.prior_nav_per_share = 9.0
    checks = {c.name: c for c in run_checks(day, compute_nav(day), reconcile(day))}
    assert checks["NAV movement"].status == "WARN"
