"""A simple NAV and the operational checks run before it is released.

NAV = market value of positions + book cash - accrued liabilities, where the
liabilities are those brought forward plus today's accruals (management fee
and expenses). A day's accrual covers every calendar day since the previous
business day, so Monday's accrual includes the weekend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from reconpilot.matching import ReconResult
from reconpilot.models import BreakKind, DayData

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# Day-on-day price move that needs a second look, by asset class. Equity moves of
# 10% and bond moves of 2% are well outside normal days and usually mean a bad
# price, a missed corporate action or a genuine event that should be confirmed.
PRICE_MOVE_LIMITS = {"EQUITY": 0.10, "BOND": 0.02}
_CASH_KINDS = {BreakKind.CASH_AMOUNT, BreakKind.CASH_MISSING_AT_CUSTODIAN, BreakKind.CASH_MISSING_IN_BOOK}


@dataclass
class NavResult:
    gross_assets: float
    cash: float
    liabilities: float
    nav: float
    nav_per_share: float
    prior_nav_per_share: float

    @property
    def movement(self) -> float:
        if not self.prior_nav_per_share:
            return 0.0
        return self.nav_per_share / self.prior_nav_per_share - 1


@dataclass
class Check:
    name: str
    status: str
    detail: str


def compute_nav(day: DayData) -> NavResult:
    gross = sum(p.quantity * p.price * day.fx_rates[p.currency] for p in day.book_positions.values())
    cash = day.book_closing_cash
    liabilities = round(day.accrued_expenses + day.accrued_today, 2)
    nav = gross + cash - liabilities
    return NavResult(
        gross_assets=round(gross, 2),
        cash=cash,
        liabilities=liabilities,
        nav=round(nav, 2),
        nav_per_share=round(nav / day.shares_outstanding, 6),
        prior_nav_per_share=day.prior_nav_per_share,
    )


def run_checks(
    day: DayData,
    nav: NavResult,
    recon: ReconResult,
    max_price_age_days: int = 1,
    movement_threshold: float = 0.02,
    cash_tolerance: float = 1.00,
    price_move_limits: dict[str, float] | None = None,
) -> list[Check]:
    checks: list[Check] = []

    cutoff = day.as_of - timedelta(days=max_price_age_days)
    stale = sorted(p.security_id for p in day.book_positions.values() if p.quantity and p.price_date < cutoff)
    checks.append(
        Check(
            "Stale prices",
            WARN if stale else PASS,
            f"{len(stale)} held position(s) priced before {cutoff}: {', '.join(stale)}" if stale
            else "All held positions priced within the allowed age.",
        )
    )

    missing = sorted(p.security_id for p in day.book_positions.values() if p.quantity and p.price <= 0)
    checks.append(
        Check(
            "Missing prices",
            FAIL if missing else PASS,
            f"No usable price for: {', '.join(missing)}" if missing else "Every held position has a price.",
        )
    )

    checks.append(price_move_check(day, price_move_limits or PRICE_MOVE_LIMITS))
    checks.append(accrual_check(day))

    move = nav.movement
    checks.append(
        Check(
            "NAV movement",
            WARN if abs(move) > movement_threshold else PASS,
            f"NAV per share moved {move:+.2%} against a threshold of {movement_threshold:.2%} "
            f"({nav.prior_nav_per_share:,.6f} to {nav.nav_per_share:,.6f}).",
        )
    )

    gap = round(day.custodian_closing_cash - day.book_closing_cash, 2)
    explained = round(
        sum(b.difference for b in recon.breaks if b.kind in _CASH_KINDS)
        + sum(m.difference for m in recon.matches),
        2,
    )
    residual = round(gap - explained, 2)
    if abs(gap) <= cash_tolerance:
        status, detail = PASS, f"Book and custodian closing cash agree within {cash_tolerance:,.2f}."
    else:
        status = FAIL if abs(residual) > cash_tolerance else WARN
        detail = (
            f"Custodian closing cash {day.custodian_closing_cash:,.2f} vs book "
            f"{day.book_closing_cash:,.2f}: gap {gap:,.2f}, of which {explained:,.2f} is explained "
            f"by open cash breaks and matched rounding, leaving {residual:,.2f} unexplained."
        )
    checks.append(Check("Cash tie-out", status, detail))
    return checks


def price_moves(day: DayData, limits: dict[str, float] | None = None) -> list[tuple[str, str, float, float]]:
    """Held positions whose book price moved more than the asset-class limit since the prior day.

    Returns (security_id, asset_class, move, limit), largest move first.
    """
    limits = limits or PRICE_MOVE_LIMITS
    out = []
    for sid, p in day.book_positions.items():
        prior = day.prior_prices.get(sid)
        if not p.quantity or not prior or prior <= 0 or p.price <= 0:
            continue
        sec = day.securities.get(sid)
        cls = sec.asset_class if sec else "EQUITY"
        limit = limits.get(cls, limits.get("EQUITY", 0.10))
        move = p.price / prior - 1
        if abs(move) > limit:
            out.append((sid, cls, move, limit))
    return sorted(out, key=lambda x: -abs(x[2]))


def price_move_check(day: DayData, limits: dict[str, float]) -> Check:
    if not day.prior_prices:
        return Check("Day-on-day price moves", PASS, "No prior-day prices supplied; check skipped.")
    flagged = price_moves(day, limits)
    if not flagged:
        text = ", ".join(f"{k.lower()} {v:.0%}" for k, v in sorted(limits.items()))
        return Check("Day-on-day price moves", PASS, f"No held position moved beyond its limit ({text}).")
    detail = "; ".join(f"{sid} ({cls.lower()}) {move:+.1%} vs limit {limit:.0%}" for sid, cls, move, limit in flagged)
    return Check("Day-on-day price moves", WARN, f"{len(flagged)} price(s) to confirm: {detail}.")


def accrual_days(as_of: date) -> int:
    """Calendar days covered by an accrual booked on ``as_of`` (3 on a Monday)."""
    prev = as_of - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return (as_of - prev).days


def expected_accruals(day: DayData) -> dict[str, float]:
    """What should have been accrued today: fee on the prior NAV, plus the expense budget."""
    days = accrual_days(day.as_of)
    prior_nav = day.prior_nav_per_share * day.shares_outstanding
    out = {}
    if day.management_fee_rate:
        out["MANAGEMENT_FEE"] = round(prior_nav * day.management_fee_rate / 365 * days, 2)
    if day.daily_expense_budget:
        out["EXPENSES"] = round(day.daily_expense_budget * days, 2)
    return out


def accrual_check(day: DayData, tolerance: float = 0.01) -> Check:
    expected = expected_accruals(day)
    if not expected:
        return Check("Accruals", PASS, "No fee or expense accruals configured for this fund.")
    booked: dict[str, float] = {}
    for a in day.accruals:
        if a.accrual_date == day.as_of:
            booked[a.kind] = booked.get(a.kind, 0.0) + a.amount
    missed, wrong = [], []
    for kind, amount in expected.items():
        got = round(booked.get(kind, 0.0), 2)
        if got == 0:
            missed.append(f"{kind.replace('_', ' ').lower()} not accrued (expected {amount:,.2f})")
        elif abs(got / amount - 1) > tolerance:
            wrong.append(f"{kind.replace('_', ' ').lower()} accrued {got:,.2f}, expected {amount:,.2f}")
    days = accrual_days(day.as_of)
    if missed:
        return Check("Accruals", FAIL, "Missed accrual: " + "; ".join(missed + wrong) + f" ({days} day(s)).")
    if wrong:
        return Check("Accruals", WARN, "Accrual differs from expected: " + "; ".join(wrong) + f" ({days} day(s)).")
    total = sum(expected.values())
    return Check("Accruals", PASS, f"Fee and expense accruals booked as expected: {total:,.2f} for {days} day(s).")
