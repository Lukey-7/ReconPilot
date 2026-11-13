from datetime import timedelta

from conftest import AS_OF, cash, make_day, trade

from reconpilot.matching import reconcile
from reconpilot.models import Category, Side
from reconpilot.triage import triage


def only_case(day):
    cases = triage(day, reconcile(day))
    assert len(cases) == 1, cases
    return cases[0]


def test_stock_split():
    day = make_day({"A": "USD"}, {"A": (1000, 90)}, holdings={"A": (3000, 30)})
    case = only_case(day)
    assert case.category is Category.STOCK_SPLIT
    assert "3-for-1" in case.explanation


def test_reverse_split():
    day = make_day({"A": "USD"}, {"A": (1000, 5)}, holdings={"A": (250, 20)})
    case = only_case(day)
    assert case.category is Category.STOCK_SPLIT
    assert "reverse" in case.explanation


def test_price_mismatch():
    day = make_day({"A": "USD"}, {"A": (1000, 100)}, holdings={"A": (1000, 103)})
    case = only_case(day)
    assert case.category is Category.PRICE_MISMATCH
    assert case.confidence >= 0.8


def test_trade_missing_from_book():
    # Custodian bought 200 at ~50 that the book never recorded.
    day = make_day({"A": "USD"}, {"A": (1000, 50)}, holdings={"A": (1200, 50)},
                   cash_lines=[cash("C1", "A", "CUS1", -10_005.0, "BUY 200 A")])
    case = only_case(day)
    assert case.category is Category.MISSING_TRADE
    assert case.confidence >= 0.9
    assert "CUS1" in case.query_draft


def test_timing_difference():
    t = trade("T1", "A", qty=200, price=50)
    late = cash("C1", "A", "T1", t.cash_amount, "PENDING SETTLEMENT", value_date=AS_OF + timedelta(days=1))
    day = make_day({"A": "USD"}, {"A": (1200, 50)}, [t], holdings={"A": (1000, 50)}, cash_lines=[late])
    case = only_case(day)
    assert case.category is Category.TIMING
    assert case.confidence >= 0.9


def test_dividend():
    day = make_day({"A": "USD"}, {"A": (1000, 50)}, cash_lines=[cash("C1", "A", "DV1", 450.0, "CASH DIVIDEND A")])
    case = only_case(day)
    assert case.category is Category.DIVIDEND
    assert "0.4500" in case.explanation


def test_dividend_without_narrative_has_lower_confidence():
    day = make_day({"A": "USD"}, {"A": (1000, 50)}, cash_lines=[cash("C1", "A", "DV1", 450.0, "CREDIT")])
    case = only_case(day)
    assert case.category is Category.DIVIDEND
    assert case.confidence < 0.9


def test_fx_difference_on_foreign_trade():
    t = trade("T1", "B", side=Side.SELL, qty=1000, price=20, ccy="EUR", fees=10.8)
    off = round(t.notional_base * 1.012 - t.fees, 2)
    day = make_day({"B": "EUR"}, {"B": (5000, 20)}, [t], cash_lines=[cash("C1", "B", "T1", off)])
    case = only_case(day)
    assert case.category is Category.FX_DIFFERENCE


def test_amount_difference_in_base_currency_is_not_fx():
    t = trade("T1", "A", qty=1000, price=20)
    day = make_day({"A": "USD"}, {"A": (5000, 20)}, [t], cash_lines=[cash("C1", "A", "T1", t.cash_amount - 150)])
    case = only_case(day)
    assert case.category is Category.UNKNOWN
    assert "commission" in case.explanation


def test_breaks_on_one_security_form_one_case():
    day = make_day({"A": "USD", "B": "USD"}, {"A": (1000, 50), "B": (10, 10)},
                   holdings={"A": (1200, 50), "B": (10, 10)},
                   cash_lines=[cash("C1", "A", "CUS1", -10_000.0)])
    cases = triage(day, reconcile(day))
    assert len(cases) == 1
    assert len(cases[0].break_ids) == 2
