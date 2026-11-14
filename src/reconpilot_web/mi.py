"""Management information and the day's exports (spec section 10, screen 5).

The ledger across days
    The command line keeps, for every run day, a ledger of every case seen so far:
    the cases cleared on earlier days, the cases cleared that day and the cases
    still open. The engine's MI (``reconpilot.mi``) is computed from those ledgers.
    ``case_snapshots`` holds only each day's own cases (cleared that day, or open
    at its end), so ``ledger_history`` rebuilds the command line's ledgers: for run
    day ``d``, every case cleared on a run day up to ``d`` (clearing days in order,
    each largest absolute impact first, the order in which the engine rolls them
    forward), then ``d``'s open cases, largest absolute impact first. A run day is
    a day with a finished run whose status is ``ready`` or ``signed_off``.

``GET .../mi``
    The engine's ``build_mi`` over those ledgers, with the gross impact (the sum of
    absolute impacts) beside every net figure, so offsetting breaks cannot hide.

Exports
    ``GET .../exports/report.xlsx`` is the engine's ``report.write_report`` for the
    day, built as the command line's ``_render`` builds it, and ``GET
    .../exports/mi.csv`` is the engine's ``write_mi_csv`` over every run day up to
    the day: the same files the command line writes for the same days. Each download
    is written to the audit log as ``EXPORT_DOWNLOADED`` with the file's hash.

Cause names are the engine's enum values; wording is the front end's job.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from reconpilot.ledger import BUCKETS, current_category
from reconpilot.matching import reconcile
from reconpilot.mi import build_mi, summarise_day, write_mi_csv
from reconpilot.models import Case
from reconpilot.nav import Check, compute_nav
from reconpilot.report import write_report
from reconpilot.storage import case_from_dict
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import current_user, get_db
from reconpilot_web.cases import has_run
from reconpilot_web.days import RUN_STATUSES, _username, get_day, parse_as_of
from reconpilot_web.funds import fund_settings, get_fund, previous_business_day
from reconpilot_web.models import BusinessDay, CaseSnapshot, Fund, User
from reconpilot_web.release import client_checks
from reconpilot_web.runner import carried_items, load_day_data

# How many run days a trend covers, as the engine's MI does.
TREND_DAYS = 20

# How many open cases the "top" list holds (the engine's MI sheet shows five).
TOP_CASES = 5

EXPORT_ACTION = "EXPORT_DOWNLOADED"
REPORT_EXPORT = "exception_report"
MI_CSV_EXPORT = "mi_csv"

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


# --------------------------------------------------------------------------- the ledger across days


def _by_impact(case: Case) -> tuple:
    return (-abs(case.nav_impact), case.case_id)  # impact.sort_by_impact


def run_days(db: Session, fund: Fund, as_of: date) -> list[date]:
    """The fund's run days up to ``as_of``, oldest first."""
    return list(db.execute(
        select(BusinessDay.as_of)
        .where(BusinessDay.fund_id == fund.id, BusinessDay.as_of <= as_of, BusinessDay.run_at.is_not(None),
               BusinessDay.status.in_(RUN_STATUSES))
        .order_by(BusinessDay.as_of)
    ).scalars())


def ledger_history(db: Session, fund: Fund, as_of: date, days: int | None = None) -> dict[str, list[Case]]:
    """The command line's ledger for each run day up to ``as_of`` (the last ``days`` of them if given).

    Keys are ISO dates, oldest first. See the module doc for how a ledger is rebuilt.
    """
    every_day = run_days(db, fund, as_of)
    wanted = every_day[-days:] if days else every_day
    if not wanted:
        return {}
    rows = db.execute(
        select(CaseSnapshot.as_of, CaseSnapshot.is_open, CaseSnapshot.data).where(
            CaseSnapshot.fund_id == fund.id,
            or_(
                and_(CaseSnapshot.is_open.is_(False), CaseSnapshot.as_of.in_(every_day)),
                and_(CaseSnapshot.is_open.is_(True), CaseSnapshot.as_of.in_(wanted)),
            ),
        )
    ).all()
    cleared: dict[date, list[Case]] = {}
    open_at: dict[date, list[Case]] = {d: [] for d in wanted}
    for snapshot_as_of, is_open, data in rows:
        (open_at[snapshot_as_of] if is_open else cleared.setdefault(snapshot_as_of, [])).append(
            case_from_dict(data))
    for cases in (*cleared.values(), *open_at.values()):
        cases.sort(key=_by_impact)

    history: dict[str, list[Case]] = {}
    for d in wanted:
        earlier = [c for day in every_day if day <= d for c in cleared.get(day, [])]
        history[str(d)] = earlier + open_at[d]
    return history


def trend_rows(history: dict[str, list[Case]]) -> list[dict[str, Any]]:
    """The engine's ``summarise_day`` for each day of ``history``, oldest first, with the gross open impact.

    ``open_gross_impact`` (the sum of the open cases' absolute impacts) sits beside the
    engine's net ``open_nav_impact``, so offsetting breaks cannot hide.
    """
    rows = []
    for d in sorted(history):
        row = asdict(summarise_day(d, history[d]))
        row["open_gross_impact"] = round(sum(abs(c.nav_impact) for c in history[d] if not c.cleared_on), 2)
        # Keep the engine's field order with the gross figure beside the net one.
        row["avg_days_to_resolve"] = row.pop("avg_days_to_resolve")
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- the MI payload


def _cell(cases: list[Case]) -> dict[str, Any]:
    return {
        "count": len(cases),
        "net": round(sum(c.nav_impact for c in cases), 2),
        "gross": round(sum(abs(c.nav_impact) for c in cases), 2),
    }


def by_cause_age(open_cases: list[Case], causes: list[str]) -> dict[str, Any]:
    """Open cases by current cause and age bucket, each cell with its count, net and gross impact."""
    def block(cases: list[Case]) -> dict[str, Any]:
        return {
            **_cell(cases),
            "cells": [{"bucket": b, **_cell([c for c in cases if c.age_bucket == b])} for b in BUCKETS],
        }

    rows = [{"cause": cause, **block([c for c in open_cases if current_category(c).value == cause])}
            for cause in causes]
    return {"buckets": list(BUCKETS), "rows": rows, "total": block(open_cases)}


def _names(db: Session, day: BusinessDay) -> dict[str, str]:
    return {sid: sec.name for sid, sec in load_day_data(db, day).securities.items()}


def _top_row(case: Case, names: dict[str, str]) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "security_id": case.security_id,
        "security_name": names.get(case.security_id, ""),
        "cause": current_category(case).value,
        "nav_impact": case.nav_impact,
        "nav_impact_bp": case.nav_impact_bp,
        "age_days": case.age_days,
        "material": case.material,
        "escalated": case.escalated,
        "sla_breached": case.sla_breached,
        "status": case.status,
    }


def _sla_row(case: Case, names: dict[str, str]) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "security_id": case.security_id,
        "security_name": names.get(case.security_id, ""),
        "cause": current_category(case).value,
        "age_days": case.age_days,
        "sla_days": case.sla_days,
        "material": case.material,
        "status": case.status,
        "cleared_on": case.cleared_on or None,
    }


def day_ran(day: BusinessDay) -> bool:
    """Whether the day has a finished run whose results stand (as the overview decides)."""
    return has_run(day) and day.status in RUN_STATUSES


def export_paths(fund: Fund, as_of: date) -> dict[str, str]:
    base = f"/api/funds/{fund.code}/days/{as_of}/exports"
    return {"report": f"{base}/report.xlsx", "mi_csv": f"{base}/mi.csv"}


def mi_payload(db: Session, fund: Fund, day: BusinessDay) -> dict[str, Any]:
    ran = day_ran(day)
    history = ledger_history(db, fund, day.as_of)
    as_of = str(day.as_of)
    # A day without a standing run is not a run day, so ``history`` stops at the day before it.
    ledger = history.get(as_of, []) if ran else []
    mi = build_mi(as_of, ledger, history, trend_days=TREND_DAYS) if ran else None
    trend = trend_rows(dict(list(history.items())[-TREND_DAYS:]))

    open_cases = sorted((c for c in ledger if not c.cleared_on), key=_by_impact)
    names = _names(db, day) if ledger else {}
    payload: dict[str, Any] = {
        "fund": {
            "code": fund.code,
            "name": fund.name,
            "base_currency": fund.base_currency,
            "materiality_bp": float(fund_settings(fund)["materiality_bp"]),
        },
        "as_of": as_of,
        "day_status": day.status,
        "has_run": ran,
        "run_days": len(history),
        "by_cause_age": by_cause_age(open_cases, mi.causes if mi else []),
        "time_to_resolve": {"rows": [], "all": {"cleared": 0, "avg_days": None}},
        "top_open": [],
        "sla_breaches": [],
        "trend": trend,
        "exports": export_paths(fund, day.as_of) if ran else None,
    }
    if mi is None:
        return payload
    payload["time_to_resolve"] = {
        "rows": [{"cause": cause, "cleared": n, "avg_days": avg} for cause, (n, avg) in sorted(
            mi.resolve_by_cause.items())],
        "all": {"cleared": sum(n for n, _ in mi.resolve_by_cause.values()), "avg_days": mi.avg_days_to_resolve},
    }
    payload["top_open"] = [_top_row(c, names) for c in mi.top_cases[:TOP_CASES]]
    payload["sla_breaches"] = [_sla_row(c, names) for c in mi.sla_breaches]
    return payload


# --------------------------------------------------------------------------- exports


def require_ran(db: Session, fund: Fund, as_of: date) -> BusinessDay:
    """The day, or 404 when it has no files, or 409 when it has no finished run to export."""
    day = get_day(db, fund, as_of)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {as_of}.")
    if not day_ran(day):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{as_of} has no finished run to export yet; run the day first.")
    return day


def _engine_checks(day: BusinessDay, open_cases: list[Case], materiality_bp: float) -> list[Check]:
    return [Check(c["name"], c["status"], c["detail"]) for c in client_checks(day.checks, open_cases, materiality_bp)]


def report_bytes(db: Session, fund: Fund, day: BusinessDay) -> tuple[bytes, int]:
    """The engine's exception report for the day, and how many run days its MI sheet drew on."""
    data = load_day_data(db, day)
    prev = previous_business_day(fund, day.as_of)
    prev_day = get_day(db, fund, prev) if prev is not None else None
    if prev_day is not None:
        data.carried_book_items, data.carried_custodian_lines = carried_items(db, prev_day)
    recon = reconcile(data)
    nav = compute_nav(data)
    history = ledger_history(db, fund, day.as_of)
    ledger = history[str(day.as_of)]
    open_cases = sorted((c for c in ledger if not c.cleared_on), key=_by_impact)
    checks = _engine_checks(day, open_cases, float(fund_settings(fund)["materiality_bp"]))
    with tempfile.TemporaryDirectory(prefix="reconpilot_report_") as tmp:
        path = write_report(Path(tmp) / "report.xlsx", data, recon, open_cases, nav, checks,
                            _username(db, day.signed_off_by) or "", ledger=ledger, history=history)
        return path.read_bytes(), len(history)


def mi_csv_bytes(db: Session, fund: Fund, day: BusinessDay) -> tuple[bytes, int]:
    """The engine's ``mi.csv`` over every run day up to the day, and how many days it covers."""
    history = ledger_history(db, fund, day.as_of)
    with tempfile.TemporaryDirectory(prefix="reconpilot_mi_") as tmp:
        return write_mi_csv(Path(tmp) / "mi.csv", history).read_bytes(), len(history)


def _download(db: Session, fund: Fund, day: BusinessDay, user: User, export: str, filename: str,
              content: bytes, days: int, media_type: str) -> Response:
    DbAuditLog(db, fund_id=fund.id).append(user.username, user.role, EXPORT_ACTION, {
        "as_of": str(day.as_of),
        "export": export,
        "filename": filename,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "run_days": days,
    })
    db.commit()
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })


# --------------------------------------------------------------------------- routes

router = APIRouter(prefix="/api/funds/{code}/days", tags=["mi"])


@router.get("/{as_of}/mi")
def read_mi(code: str, as_of: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Management information for the fund up to the day (see module doc). Any signed-in role."""
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    day = get_day(db, fund, day_date)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {day_date}.")
    return mi_payload(db, fund, day)


@router.get("/{as_of}/exports/report.xlsx")
def export_report(code: str, as_of: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> Response:
    """The day's exception report as an Excel workbook, audited. Any signed-in role."""
    fund = get_fund(db, code)
    day = require_ran(db, fund, parse_as_of(as_of))
    content, days = report_bytes(db, fund, day)
    return _download(db, fund, day, user, REPORT_EXPORT, f"exceptions_{fund.code}_{day.as_of}.xlsx",
                     content, days, XLSX_MEDIA_TYPE)


@router.get("/{as_of}/exports/mi.csv")
def export_mi_csv(code: str, as_of: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> Response:
    """MI in the engine's tidy form for every run day up to the day, audited. Any signed-in role."""
    fund = get_fund(db, code)
    day = require_ran(db, fund, parse_as_of(as_of))
    content, days = mi_csv_bytes(db, fund, day)
    return _download(db, fund, day, user, MI_CSV_EXPORT, f"mi_{fund.code}_{day.as_of}.csv",
                     content, days, CSV_MEDIA_TYPE)
