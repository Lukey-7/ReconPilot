"""The morning overview of a fund's business day (spec 10, screen 1).

One response holds what the overview screen shows, all computed on the server
from the day's stored run, so the screen never works a figure out for itself:

* the NAV and the release checks, and the day's one release status, computed
  by the same functions as ``GET .../release`` so the two never disagree;
* "every break accounted for": the breaks the run found, how many sit in an
  open case, and how many of the open cases are decided or still pending;
* the open cases by NAV impact with **gross and net** totals (net alone would
  let offsetting breaks hide each other);
* ageing buckets, SLA breaches, escalations and the cases cleared today;
* the trend of open, new and cleared cases per run day (the engine's
  ``mi.summarise_day`` over the day ledgers that ``reconpilot_web.mi`` rebuilds).

Cause names and statuses are the engine's enum values; wording is the front
end's job.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reconpilot.ledger import BUCKETS
from reconpilot.models import Case
from reconpilot.storage import case_from_dict
from reconpilot_web.auth import current_user, get_db
from reconpilot_web.cases import case_item, case_versions, has_run
from reconpilot_web.days import RUN_STATUSES, _username, get_day, parse_as_of
from reconpilot_web.funds import fund_settings, get_fund
from reconpilot_web.mi import TREND_DAYS, ledger_history, trend_rows
from reconpilot_web.models import BreakRow, BusinessDay, CaseSnapshot, Fund, User
from reconpilot_web.release import client_checks, compute_release
from reconpilot_web.runner import load_day_data

DECIDED_STATUSES = ("APPROVED", "REJECTED", "RECLASSIFIED")


def overview_case(case: Case, version: int | None, security_name: str = "") -> dict[str, Any]:
    """A case as the overview lists it: the queue row plus who decided it and its lifecycle."""
    return {
        **case_item(case, version, security_name),
        "reviewed_by": case.reviewed_by,
        "reviewed_role": case.reviewed_role,
        "review_note": case.review_note,
        "first_seen": case.first_seen,
        "sla_days": case.sla_days,
        "escalation_reason": case.escalation_reason,  # the impact at escalation, not today's
    }


def _snapshots(db: Session, fund: Fund, as_of: date) -> list[CaseSnapshot]:
    return list(db.execute(
        select(CaseSnapshot).where(CaseSnapshot.fund_id == fund.id, CaseSnapshot.as_of == as_of)
    ).scalars())


def _ledger(snapshots: list[CaseSnapshot]) -> tuple[list[Case], list[Case]]:
    """``(open, cleared)`` cases of one day's ledger; open ones largest absolute impact first."""
    open_cases = [case_from_dict(s.data) for s in snapshots if s.is_open]
    cleared = [case_from_dict(s.data) for s in snapshots if not s.is_open]
    open_cases.sort(key=lambda c: (-abs(c.nav_impact), c.case_id))  # impact.sort_by_impact
    cleared.sort(key=lambda c: c.case_id)
    return open_cases, cleared


def accounted_for(db: Session, day: BusinessDay, open_cases: list[Case]) -> dict[str, int]:
    """Every break the run found, where it sits, and how far its case has got."""
    found, in_cases = db.execute(
        select(func.count(BreakRow.id), func.count(BreakRow.case_id)).where(BreakRow.business_day_id == day.id)
    ).one()
    by_status = {s: sum(1 for c in open_cases if c.status == s) for s in (*DECIDED_STATUSES, "PENDING")}
    return {
        "breaks_found": found,
        "breaks_in_cases": in_cases,
        "breaks_not_in_case": found - in_cases,
        "open_cases": len(open_cases),
        "decided": sum(by_status[s] for s in DECIDED_STATUSES),
        "approved": by_status["APPROVED"],
        "rejected": by_status["REJECTED"],
        "reclassified": by_status["RECLASSIFIED"],
        "pending": by_status["PENDING"],
    }


def impact_totals(open_cases: list[Case]) -> dict[str, Any]:
    """Net and gross NAV impact of the open cases (gross: offsetting impacts cannot cancel)."""
    return {
        "net": round(sum(c.nav_impact for c in open_cases), 2),
        "gross": round(sum(abs(c.nav_impact) for c in open_cases), 2),
        "gross_exposure": round(sum(c.gross_exposure for c in open_cases), 2),
        "material": sum(1 for c in open_cases if c.material),
    }


def ageing(open_cases: list[Case]) -> list[dict[str, Any]]:
    """The open cases by age bucket (business days open), always all three buckets."""
    out = []
    for bucket in BUCKETS:
        cases = [c for c in open_cases if c.age_bucket == bucket]
        out.append({
            "bucket": bucket,
            "count": len(cases),
            "net": round(sum(c.nav_impact for c in cases), 2),
            "gross": round(sum(abs(c.nav_impact) for c in cases), 2),
        })
    return out


def trend(db: Session, fund: Fund, as_of: date, days: int = TREND_DAYS) -> list[dict[str, Any]]:
    """Open, new and cleared cases for each run day up to ``as_of`` (at most ``days``), oldest first.

    Computed from the command line's ledgers (every case seen so far), so the average
    time to resolve covers every case cleared up to each day, as on the MI screen.
    """
    return trend_rows(ledger_history(db, fund, as_of, days))


def overview_payload(db: Session, fund: Fund, day: BusinessDay) -> dict[str, Any]:
    settings = fund_settings(fund)
    materiality_bp = float(settings["materiality_bp"])
    # The same cases the release route reads (any finished run), so status and checks match it.
    open_cases, cleared = _ledger(_snapshots(db, fund, day.as_of)) if has_run(day) else ([], [])
    release_status = compute_release(day, open_cases, day.checks or [])
    ran = has_run(day) and day.status in RUN_STATUSES
    payload: dict[str, Any] = {
        "fund": {
            "code": fund.code,
            "name": fund.name,
            "base_currency": fund.base_currency,
            "materiality_bp": materiality_bp,
        },
        "as_of": str(day.as_of),
        "day_status": day.status,
        "has_run": ran,
        "run_at": day.run_at.isoformat() if day.run_at else None,
        "run_by": _username(db, day.run_by),
        "signed_off_by": _username(db, day.signed_off_by),
        "signed_off_at": day.signed_off_at.isoformat() if day.signed_off_at else None,
        "nav": None,
        "checks": client_checks(day.checks, open_cases, materiality_bp),
        "release": release_status.to_dict(),
        "run": None,
        "accounted": None,
        "impact": None,
        "ageing": ageing(open_cases if ran else []),
        "sla_breaches": [],
        "escalations": [],
        "cleared_today": [],
        "trend": trend(db, fund, day.as_of),
    }
    if not ran:
        return payload

    detail = day.nav_detail or {}
    payload["nav"] = {
        "nav": day.nav,
        "nav_per_share": day.nav_per_share,
        "prior_nav_per_share": day.prior_nav_per_share,
        "movement": detail.get("movement"),
        "gross_assets": detail.get("gross_assets"),
        "cash": detail.get("cash"),
        "liabilities": detail.get("liabilities"),
    }
    summary = day.summary or {}
    payload["run"] = {key: summary.get(key) for key in ("matches", "breaks", "new_cases", "carried_cases")}

    names = {sid: sec.name for sid, sec in load_day_data(db, day).securities.items()} if (
        open_cases or cleared) else {}
    versions = case_versions(db, fund, [c.case_id for c in open_cases + cleared])
    rows = [overview_case(c, versions.get(c.case_id), names.get(c.security_id, "")) for c in open_cases]
    payload["accounted"] = accounted_for(db, day, open_cases)
    payload["impact"] = {"cases": rows, **impact_totals(open_cases)}
    payload["sla_breaches"] = [r for r in rows if r["sla_breached"]]
    payload["escalations"] = [r for r in rows if r["escalated"]]
    payload["cleared_today"] = [
        {
            "case_id": c.case_id,
            "security_id": c.security_id,
            "security_name": names.get(c.security_id, ""),
            "category": c.category.value,
            "final_category": c.final_category.value if c.final_category else None,
            "resolved_category": c.resolved_category.value if c.resolved_category else None,
            "status": c.status,
            "clear_reason": c.clear_reason,
            "nav_impact": c.nav_impact,
            "age_days": c.age_days,
            "first_seen": c.first_seen,
            "cleared_on": c.cleared_on,
        }
        for c in cleared
    ]
    return payload


# --------------------------------------------------------------------------- routes

router = APIRouter(prefix="/api/funds/{code}/days", tags=["overview"])


@router.get("/{as_of}/overview")
def read_overview(code: str, as_of: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The morning overview for the day (see module doc); 404 when the day has no files."""
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    day = get_day(db, fund, day_date)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {day_date}.")
    return overview_payload(db, fund, day)
