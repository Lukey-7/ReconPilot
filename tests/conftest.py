from datetime import date

import pytest

from reconpilot.models import (
    CashLine,
    DayData,
    Holding,
    Position,
    Security,
    Side,
    Trade,
)

AS_OF = date(2026, 11, 13)
FX = {"USD": 1.0, "EUR": 1.08}


def trade(trade_id, sid, side=Side.BUY, qty=100.0, price=50.0, ccy="USD", fees=0.0, settle=AS_OF):
    return Trade(trade_id, date(2026, 11, 11), settle, sid, side, qty, price, ccy, FX[ccy], fees)


def cash(entry, sid, ref, amount, desc="", value_date=AS_OF):
    return CashLine(entry, value_date, sid, ref, desc, amount)


def make_day(securities, positions, trades=(), holdings=None, cash_lines=()):
    """Build a small day. ``positions`` maps sid -> (qty, price); holdings default to the same."""
    secs = {sid: Security(sid, f"Name {sid}", ccy) for sid, ccy in securities.items()}
    book = {sid: Position(sid, q, p, AS_OF, secs[sid].currency) for sid, (q, p) in positions.items()}
    hold_src = holdings if holdings is not None else positions
    cust = {sid: Holding(sid, q, p, secs[sid].currency) for sid, (q, p) in hold_src.items()}
    return DayData(
        as_of=AS_OF,
        securities=secs,
        fx_rates=dict(FX),
        book_trades=list(trades),
        book_positions=book,
        custodian_holdings=cust,
        custodian_cash=list(cash_lines),
        book_opening_cash=1_000_000.0,
        custodian_opening_cash=1_000_000.0,
        prior_nav_per_share=10.0,
        shares_outstanding=100_000.0,
        accrued_expenses=0.0,
    )


@pytest.fixture
def day_factory():
    return make_day
