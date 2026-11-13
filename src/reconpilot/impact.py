"""NAV impact and materiality of each case.

A case's NAV impact is how much the NAV would move if the custodian's view
turned out to be right and the book were corrected to it: the change in
market value of the position plus the cash difference, in base currency.
That is the number operations teams rank breaks by.

Two consequences worth knowing:

* A missing or late trade moves position and cash in opposite directions, so
  its net impact is small (fees and the price move since the trade) even when
  the trade itself is large. ``gross_exposure`` keeps the size of the
  underlying items for context.
* A stock split the book has not applied has almost no NAV impact, because
  quantity and price move by the same factor. It still ages and escalates
  like any other break.

Cases at or above the materiality threshold (default 1 basis point of NAV)
are material: they are escalated and block NAV release until approved.
"""

from __future__ import annotations

from reconpilot.matching import ReconResult
from reconpilot.models import BreakKind, Case, DayData
from reconpilot.nav import FAIL, PASS, Check, NavResult

DEFAULT_MATERIALITY_BP = 1.0
RESOLVED = ("APPROVED", "RECLASSIFIED")
_CASH_KINDS = {BreakKind.CASH_AMOUNT, BreakKind.CASH_MISSING_AT_CUSTODIAN, BreakKind.CASH_MISSING_IN_BOOK}


def case_impact(day: DayData, recon: ReconResult, case: Case) -> tuple[float, float]:
    """Return (net NAV impact, gross exposure) in base currency."""
    ids = set(case.break_ids)
    breaks = [b for b in recon.breaks if b.break_id in ids]
    sec = day.securities.get(case.security_id)
    fx = day.fx_rates.get(sec.currency, 1.0) if sec else 1.0
    pos = day.book_positions.get(case.security_id)
    hold = day.custodian_holdings.get(case.security_id)

    position_impact = 0.0
    gross = 0.0
    kinds = {b.kind for b in breaks}
    if kinds & {BreakKind.QUANTITY, BreakKind.PRICE}:
        book_mv = (pos.quantity * pos.price * fx) if pos else 0.0
        cust_mv = (hold.quantity * hold.price * fx) if hold else 0.0
        position_impact = cust_mv - book_mv
        price = pos.price if pos and pos.price else (hold.price if hold else 0.0)
        for b in breaks:
            if b.kind is BreakKind.QUANTITY:
                gross += abs(b.difference) * price * fx
            elif b.kind is BreakKind.PRICE:
                gross += abs(b.difference) * (pos.quantity if pos else 0.0) * fx
    cash_impact = sum(b.difference for b in breaks if b.kind in _CASH_KINDS)
    gross += sum(abs(b.difference) for b in breaks if b.kind in _CASH_KINDS)
    return round(position_impact + cash_impact, 2), round(gross, 2)


def apply_impacts(
    day: DayData,
    recon: ReconResult,
    cases: list[Case],
    nav: NavResult,
    materiality_bp: float = DEFAULT_MATERIALITY_BP,
) -> list[Case]:
    """Set impact fields on every case and return them sorted, largest impact first."""
    for case in cases:
        impact, gross = case_impact(day, recon, case)
        case.nav_impact = impact
        case.gross_exposure = gross
        case.nav_impact_bp = round(impact / nav.nav * 10_000, 4) if nav.nav else 0.0
        case.material = abs(case.nav_impact_bp) >= materiality_bp
    return sort_by_impact(cases)


def sort_by_impact(cases: list[Case]) -> list[Case]:
    return sorted(cases, key=lambda c: (-abs(c.nav_impact), c.case_id))


def blocking_cases(cases: list[Case]) -> list[Case]:
    """Material cases that have not been approved or reclassified yet."""
    return [c for c in cases if c.material and not c.cleared_on and c.status not in RESOLVED]


def release_check(cases: list[Case], materiality_bp: float = DEFAULT_MATERIALITY_BP) -> Check:
    blocked = blocking_cases(cases)
    if not blocked:
        material = sum(1 for c in cases if c.material and not c.cleared_on)
        return Check("NAV release", PASS,
                     f"No material case awaiting approval ({material} material case(s) approved; "
                     f"threshold {materiality_bp:g} bp of NAV).")
    total = sum(c.nav_impact for c in blocked)
    worst = ", ".join(f"{c.case_id} ({c.nav_impact_bp:+.2f} bp)" for c in sort_by_impact(blocked)[:5])
    return Check("NAV release", FAIL,
                 f"Blocked: {len(blocked)} material case(s) awaiting approval, net impact {total:,.2f} "
                 f"(threshold {materiality_bp:g} bp of NAV): {worst}.")
