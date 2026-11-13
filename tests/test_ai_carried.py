"""AI evidence and flags for cases carried across days, and whole-number quantities."""

import json
from datetime import timedelta

import pytest
from conftest import AS_OF, cash, make_day, trade

from reconpilot import ai
from reconpilot.ai import DISAGREEMENT_FLAG, build_evidence
from reconpilot.ledger import load_open_items, save_open_items
from reconpilot.matching import carry_forward, reconcile
from reconpilot.models import Category
from reconpilot.pipeline import run_day
from reconpilot.triage import triage

MON = AS_OF + timedelta(days=3)  # 2026-11-13 is a Friday


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr(ai.urllib.request, "urlopen", refuse)
    for var in ai.KEY_ENV.values():
        monkeypatch.delenv(var, raising=False)


class FakeClient:
    provider = "fake"
    effort = "medium"
    model = "fake-1"

    def __init__(self, category):
        self.category = category

    def complete(self, system, user):
        return json.dumps({
            "category": self.category,
            "confidence": 0.6,
            "explanation": "The evidence on file does not settle the cause on its own.",
            "investigation_steps": ["Ask the custodian for the settlement detail.", "Check the trade blotter."],
            "custodian_query": "Subject: Settlement query\n\nHello, please send the settlement detail.",
        })


def fx_days(client_day1=None, client_day2=None):
    """Day 1: a EUR trade settles 1% off at the custodian. Day 2: the pair is carried, no trades."""
    t1 = trade("T1", "E", qty=100, price=50, ccy="EUR")
    line = cash("C1", "E", "T1", round(t1.cash_amount * 1.01, 2), "TRADE SETTLEMENT")
    fri = make_day({"E": "EUR"}, {"E": (1000, 50)}, [t1], cash_lines=[line])
    day1 = run_day(fri, use_ai=client_day1 is not None, ai_client=client_day1)

    mon = make_day({"E": "EUR"}, {"E": (1000, 50)})
    mon.as_of = MON
    mon.carried_book_items, mon.carried_custodian_lines = carry_forward(day1.recon, day1.day)
    day2 = run_day(mon, day1.open_cases, use_ai=client_day2 is not None, ai_client=client_day2)
    return t1, day1, day2


def test_carried_fx_case_evidence_includes_original_trade():
    t1, day1, day2 = fx_days()
    assert day1.open_cases[0].category is Category.FX_DIFFERENCE
    ev = build_evidence(day2.day, day2.recon, day2.open_cases[0])
    assert [t["trade_id"] for t in ev["book_trades"]] == ["T1"]
    assert ev["book_trades"][0]["settlement_cash_base"] == t1.cash_amount


def test_whole_quantities_are_integers_in_evidence():
    t = trade("T7", "A", qty=900, price=12.5)
    day = make_day({"A": "USD"}, {"A": (25900.0, 12.5)}, [t], holdings={"A": (25000.0, 12.5)})
    recon = reconcile(day)
    case = triage(day, recon)[0]
    ev = build_evidence(day, recon, case)

    assert ev["book_position"]["quantity"] == 25900 and isinstance(ev["book_position"]["quantity"], int)
    assert isinstance(ev["custodian_holding"]["quantity"], int)
    qty_break = next(b for b in ev["breaks"] if b["kind"] == "QUANTITY")
    assert isinstance(qty_break["book_value"], int) and isinstance(qty_break["custodian_value"], int)
    assert isinstance(ev["book_trades"][0]["quantity"], int)
    assert isinstance(ev["book_position"]["price"], float)  # prices are left alone
    assert "25900.0" not in ai.build_prompt(ev)


def test_disagreement_flag_recomputed_after_carried_diagnosis():
    _, day1, day2 = fx_days(FakeClient("FX_DIFFERENCE"), FakeClient("UNKNOWN"))
    assert day1.open_cases[0].ai_flag == ""
    case = day2.open_cases[0]
    assert case.category is Category.FX_DIFFERENCE and case.ai_category is Category.UNKNOWN
    assert case.ai_flag == DISAGREEMENT_FLAG


def test_carried_agreement_is_not_flagged():
    _, _, day2 = fx_days(FakeClient("FX_DIFFERENCE"), FakeClient("FX_DIFFERENCE"))
    case = day2.open_cases[0]
    assert case.category is Category.FX_DIFFERENCE and case.ai_category is Category.FX_DIFFERENCE
    assert case.ai_flag == ""


def test_open_items_round_trip_keeps_trade(tmp_path):
    t1, day1, _ = fx_days()
    save_open_items(tmp_path, AS_OF, day1.recon, day1.day)
    book, cust = load_open_items(tmp_path, AS_OF)
    assert [i.reference for i in book] == ["T1"]
    assert book[0].trade == t1
    assert [c.entry_id for c in cust] == ["C1"]

    # Without the day, as older runs were saved, the trade is simply absent.
    save_open_items(tmp_path, AS_OF, day1.recon)
    book, _ = load_open_items(tmp_path, AS_OF)
    assert book[0].trade is None
