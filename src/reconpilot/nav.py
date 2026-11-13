"""A simple NAV and the operational checks run before it is released."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from reconpilot.matching import ReconResult
from reconpilot.models import BreakKind, DayData

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
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
    nav = gross + cash - day.accrued_expenses
    return NavResult(
        gross_assets=round(gross, 2),
        cash=cash,
        liabilities=day.accrued_expenses,
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
