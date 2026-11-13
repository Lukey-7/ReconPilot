"""Engine interfaces the web layer relies on: check settings, case serialisers, the audit hash."""

import json
from dataclasses import fields

import pytest
from conftest import make_day

from reconpilot.audit import AuditLog, record_hash
from reconpilot.models import Case, Category
from reconpilot.pipeline import run_day
from reconpilot.storage import case_from_dict, case_to_dict, load_cases, save_cases


def _price_move_check(result):
    return next(c for c in result.checks if c.name == "Day-on-day price moves")


def test_check_settings_change_price_move_limit():
    day = make_day({"A": "USD"}, {"A": (1000, 103.0)})
    day.prior_prices = {"A": 100.0}  # a 3% equity move

    assert _price_move_check(run_day(day)).status == "PASS"
    tight = {"price_move_limits": {"EQUITY": 0.02, "BOND": 0.02}}
    assert _price_move_check(run_day(day, check_settings=tight)).status == "WARN"


def test_check_settings_reach_movement_threshold_and_cash_tolerance():
    day = make_day({"A": "USD"}, {"A": (1000, 50)})
    day.custodian_opening_cash += 5.0  # a 5.00 unexplained cash gap
    nav_move = next(c for c in run_day(day).checks if c.name == "NAV movement")
    cash = next(c for c in run_day(day).checks if c.name == "Cash tie-out")
    assert cash.status == "FAIL"

    relaxed = run_day(day, check_settings={"cash_tolerance": 10.0, "movement_threshold": 0.5})
    assert next(c for c in relaxed.checks if c.name == "Cash tie-out").status == "PASS"
    assert "50.00%" in next(c for c in relaxed.checks if c.name == "NAV movement").detail
    assert "2.00%" in nav_move.detail


def test_check_settings_reject_unknown_keys():
    day = make_day({"A": "USD"}, {"A": (1000, 50)})
    with pytest.raises(ValueError, match="materiality"):
        run_day(day, check_settings={"materiality": 2.0})


def _full_case() -> Case:
    return Case(
        case_id="C0007", security_id="A", category=Category.FX_DIFFERENCE, confidence=0.85,
        explanation="Settled 1% off.", query_draft="Subject: FX\n\nHello.", break_ids=["B0001", "B0002"],
        status="RECLASSIFIED", final_category=Category.TIMING, reviewed_by="ana", review_note="late",
        ai_category=Category.UNKNOWN, ai_confidence=0.4, ai_explanation="Unclear.", ai_steps=["a", "b"],
        ai_query="Subject: Q", ai_model="fake-1", ai_status="ACCEPTED", ai_flag="AI disagrees: needs review",
        ai_fallback_reason="none", nav_impact=-54.0, nav_impact_bp=-0.5, gross_exposure=54.0, material=True,
        break_kinds=["CASH_AMOUNT"], first_seen="2026-11-13", age_days=3, age_bucket="2-5", escalated=True,
        escalation_reason="material (-0.50 bp of NAV)", sla_days=2, sla_breached=True, cleared_on="2026-11-18",
        clear_reason="agree again", resolved_category=Category.TIMING, reviewed_role="approver",
    )


def test_case_dict_round_trip(tmp_path):
    case = _full_case()
    d = case_to_dict(case)
    assert json.loads(json.dumps(d)) == d  # JSON-safe
    assert d["category"] == "FX_DIFFERENCE" and d["ai_category"] == "UNKNOWN"
    assert d["final_category"] == "TIMING" and d["resolved_category"] == "TIMING"

    back = case_from_dict(json.loads(json.dumps(d)))
    for f in fields(Case):
        assert getattr(back, f.name) == getattr(case, f.name), f.name
    assert back.ai_category is Category.UNKNOWN and back.resolved_category is Category.TIMING

    empty = Case("C1", "B", Category.UNKNOWN, 0.0, "", "")
    assert case_from_dict(case_to_dict(empty)) == empty

    save_cases([case, empty], tmp_path / "cases.json")
    assert load_cases(tmp_path / "cases.json") == [case, empty]


def test_record_hash_matches_audit_log(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("ana", "analyst", "RUN_STARTED", {"as_of": "2026-11-13"})
    entry = log.append("ana", "analyst", "CASE_APPROVED", {"case_id": "C0001", "amount": 12.5})
    body = {k: v for k, v in entry.items() if k != "hash"}
    assert record_hash(body) == entry["hash"]
    stored = log.entries()[-1]
    assert record_hash({k: v for k, v in stored.items() if k != "hash"}) == stored["hash"]
