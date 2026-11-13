from conftest import cash, make_day, trade

from reconpilot.matching import reconcile
from reconpilot.models import BreakKind, Side


def kinds(result):
    return sorted(b.kind for b in result.breaks)


def test_clean_day_has_no_breaks():
    t = trade("T1", "A", qty=100, price=50)
    day = make_day({"A": "USD"}, {"A": (100, 50)}, [t], cash_lines=[cash("C1", "A", "T1", -5000.0)])
    result = reconcile(day)
    assert result.breaks == []
    assert [m.kind for m in result.matches] == ["EXACT"]


def test_small_rounding_is_matched_within_tolerance():
    t = trade("T1", "A", qty=100, price=50)
    day = make_day({"A": "USD"}, {"A": (100, 50)}, [t], cash_lines=[cash("C1", "A", "T1", -5000.37)])
    result = reconcile(day)
    assert result.breaks == []
    assert result.matches[0].kind == "TOLERANCE"


def test_line_without_reference_matches_on_security_and_amount():
    t = trade("T1", "A", qty=100, price=50)
    day = make_day({"A": "USD"}, {"A": (100, 50)}, [t], cash_lines=[cash("C1", "A", "", -5000.10)])
    result = reconcile(day)
    assert result.breaks == []
    assert result.matches[0].kind == "ATTRIBUTE"


def test_netted_custodian_line_matches_many_to_one():
    trades = [
        trade("T1", "A", qty=100, price=50),
        trade("T2", "A", side=Side.SELL, qty=40, price=51),
        trade("T3", "A", qty=10, price=49),
    ]
    net = sum(t.cash_amount for t in trades)
    day = make_day({"A": "USD"}, {"A": (1000, 50)}, trades, cash_lines=[cash("C1", "A", "NET-A", net + 0.2)])
    result = reconcile(day)
    assert result.breaks == []
    assert result.matches[0].kind == "MANY_TO_ONE"
    assert sorted(result.matches[0].book_refs) == ["T1", "T2", "T3"]


def test_amount_outside_tolerance_is_a_cash_amount_break():
    t = trade("T1", "A", qty=100, price=50)
    day = make_day({"A": "USD"}, {"A": (100, 50)}, [t], cash_lines=[cash("C1", "A", "T1", -5040.0)])
    result = reconcile(day)
    assert kinds(result) == [BreakKind.CASH_AMOUNT]
    assert result.breaks[0].difference == -40.0


def test_position_quantity_and_price_breaks():
    day = make_day({"A": "USD", "B": "USD"}, {"A": (100, 50), "B": (200, 10)},
                   holdings={"A": (150, 50), "B": (200, 10.5)})
    result = reconcile(day)
    assert kinds(result) == sorted([BreakKind.QUANTITY, BreakKind.PRICE])
    assert {b.security_id for b in result.breaks if b.kind is BreakKind.PRICE} == {"B"}


def test_price_within_tolerance_is_ignored():
    day = make_day({"A": "USD"}, {"A": (100, 100)}, holdings={"A": (100, 100.2)})
    assert reconcile(day).breaks == []


def test_unmatched_cash_on_each_side_and_pending_lines():
    t = trade("T1", "A", qty=100, price=50)
    lines = [cash("C1", "B", "X9", 120.0), cash("C2", "A", "T1", -5000.0, value_date=t.settle_date.replace(day=14))]
    day = make_day({"A": "USD", "B": "USD"}, {"A": (100, 50), "B": (10, 1)}, [t], cash_lines=lines)
    result = reconcile(day)
    assert kinds(result) == [BreakKind.CASH_MISSING_AT_CUSTODIAN, BreakKind.CASH_MISSING_IN_BOOK]
    assert [p.entry_id for p in result.pending] == ["C2"]
