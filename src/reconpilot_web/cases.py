"""The case queue, a case's detail and evidence, and decisions (spec 7, 9 and 10).

Reading
    A day's queue is its open cases as they stood at the end of that day (the
    ``case_snapshots`` ledger), largest absolute NAV impact first, exactly as the
    engine orders them. ``version`` is the case's current version, which a
    decision must quote. A case's detail adds the evidence behind it from the
    day's stored files: its breaks, the book position and custodian holding, the
    book trades and custodian cash lines that concern it, and its history (every
    decision and audit entry for the case, oldest first) and the case across days
    (how it stood at the end of every day it was in a run, from ``case_snapshots``).

Deciding
    Analysts and approvers approve, reject (with a note) or reclassify (with a
    cause) a case through the engine's own ``ReviewSession``, which writes the
    ``CASE_*`` audit entry. The decision, the case's new state, the day's ledger
    snapshot of it and the audit entry are written in one transaction, as the
    command line's ``reconpilot review`` updates ``cases.json`` and the ledger.

    Every decision quotes the ``version`` it was made against. The day is locked
    first and the case second (the order the runner and sign-off use), so two
    people deciding the same case at once queue up: the first decision stands
    and bumps the version, the second finds its version stale and is refused
    with 409, never silently overwriting the first (spec 9). A decision is also
    refused with 409 once the day is signed off, while it is being run, or when
    the case has cleared.

Cause names and statuses are the engine's enum values (``MISSING_TRADE``,
``PENDING``, ...); human wording is the front end's job.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from reconpilot.ledger import BUCKETS, current_category
from reconpilot.models import Case, Category, DayData
from reconpilot.review import PermissionDenied, ReviewError, ReviewSession
from reconpilot.storage import case_from_dict, case_to_dict, trade_to_dict
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import current_user, get_db, require_roles
from reconpilot_web.days import get_day, parse_as_of
from reconpilot_web.funds import get_fund, previous_business_day
from reconpilot_web.models import (
    AuditEntry,
    BreakRow,
    BusinessDay,
    CaseRow,
    CaseSnapshot,
    Decision,
    Fund,
    OpenItem,
    User,
)
from reconpilot_web.runner import _case_columns, cash_line_to_dict, load_day_data

STATUSES = ("PENDING", "APPROVED", "REJECTED", "RECLASSIFIED")
MAX_NOTE_LENGTH = 2000

# The fields of a case in the queue (and at the top of its detail).
QUEUE_FIELDS = (
    "case_id", "security_id", "security_name", "category", "ai_category", "ai_flag", "status",
    "final_category", "nav_impact", "nav_impact_bp", "gross_exposure", "material", "escalated",
    "sla_breached", "age_days", "age_bucket", "version",
)


# --------------------------------------------------------------------------- loading


def has_run(day: BusinessDay | None) -> bool:
    """Whether the day has a finished run whose cases can be read."""
    return day is not None and day.run_at is not None


def require_run_day(db: Session, fund: Fund, as_of: date) -> BusinessDay:
    """The day, or 404 if nothing was uploaded for it, or 409 if it has never finished a run."""
    day = get_day(db, fund, as_of)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {as_of}.")
    if not has_run(day):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{as_of} has not been run yet.")
    return day


def open_cases_for_day(db: Session, fund: Fund, as_of: date) -> list[Case]:
    """The cases open at the end of ``as_of``, largest absolute NAV impact first."""
    rows = db.execute(
        select(CaseSnapshot.data)
        .where(CaseSnapshot.fund_id == fund.id, CaseSnapshot.as_of == as_of, CaseSnapshot.is_open.is_(True))
    ).scalars().all()
    cases = [case_from_dict(data) for data in rows]
    return sorted(cases, key=lambda c: (-abs(c.nav_impact), c.case_id))  # impact.sort_by_impact


def case_versions(db: Session, fund: Fund, case_ids: list[str]) -> dict[str, int]:
    if not case_ids:
        return {}
    rows = db.execute(
        select(CaseRow.case_id, CaseRow.version).where(CaseRow.fund_id == fund.id, CaseRow.case_id.in_(case_ids))
    ).all()
    return {case_id: version for case_id, version in rows}


def _cat(value: Category | None) -> str | None:
    return value.value if value is not None else None


def case_item(case: Case, version: int | None, security_name: str = "") -> dict[str, Any]:
    """A case as one row of the queue."""
    return {
        "case_id": case.case_id,
        "security_id": case.security_id,
        "security_name": security_name,
        "category": case.category.value,
        "ai_category": _cat(case.ai_category),
        "ai_flag": case.ai_flag,
        "status": case.status,
        "final_category": _cat(case.final_category),
        "nav_impact": case.nav_impact,
        "nav_impact_bp": case.nav_impact_bp,
        "gross_exposure": case.gross_exposure,
        "material": case.material,
        "escalated": case.escalated,
        "sla_breached": case.sla_breached,
        "age_days": case.age_days,
        "age_bucket": case.age_bucket,
        "version": version,
    }


def _security_names(data: DayData) -> dict[str, str]:
    return {sid: sec.name for sid, sec in data.securities.items()}


# --------------------------------------------------------------------------- filters


def _choices(value: str | None, allowed: tuple[str, ...], name: str) -> set[str] | None:
    """A comma-separated filter value as a set of allowed values (case-insensitive), or 422."""
    if value is None or not value.strip():
        return None
    chosen = {v.strip().upper() for v in value.split(",") if v.strip()}
    bad = sorted(chosen - set(allowed))
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Unknown {name}: {', '.join(bad)}. Allowed: {', '.join(allowed)}.")
    return chosen


def filter_cases(
    items: list[dict[str, Any]],
    *,
    statuses: set[str] | None = None,
    categories: set[str] | None = None,
    material: bool | None = None,
    escalated: bool | None = None,
    sla: bool | None = None,
    age: set[str] | None = None,
    ai_disagrees: bool | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    """Queue rows that pass every filter given. ``categories`` matches the suggested or the final cause."""
    needle = (q or "").strip().lower()
    out = []
    for item in items:
        if statuses is not None and item["status"] not in statuses:
            continue
        if categories is not None and not ({item["category"], item["final_category"]} & categories):
            continue
        if material is not None and item["material"] is not material:
            continue
        if escalated is not None and item["escalated"] is not escalated:
            continue
        if sla is not None and item["sla_breached"] is not sla:
            continue
        if age is not None and item["age_bucket"] not in age:
            continue
        if ai_disagrees is not None and bool(item["ai_flag"]) is not ai_disagrees:
            continue
        if needle and not any(needle in str(item[k]).lower() for k in ("case_id", "security_id", "security_name")):
            continue
        out.append(item)
    return out


# --------------------------------------------------------------------------- detail


def _plain(value: Any) -> Any:
    """A dataclass (or anything) as plain JSON values; dates become ISO strings."""
    return json.loads(json.dumps(asdict(value) if hasattr(value, "__dataclass_fields__") else value, default=str))


def _username(db: Session, user_id: int | None, cache: dict[int, str]) -> str | None:
    if user_id is None:
        return None
    if user_id not in cache:
        user = db.get(User, user_id)
        cache[user_id] = user.username if user else str(user_id)
    return cache[user_id]


def case_history(db: Session, fund: Fund, case_id: str) -> list[dict[str, Any]]:
    """Every decision and audit entry for the case, oldest first."""
    names: dict[int, str] = {}
    events: list[tuple[datetime, int, int, dict[str, Any]]] = []
    for e in db.execute(
        select(AuditEntry).where(AuditEntry.fund_id == fund.id, AuditEntry.case_id == case_id)
        .order_by(AuditEntry.seq)
    ).scalars():
        at = datetime.fromisoformat(e.ts)
        events.append((at, 0, e.seq, {
            "type": "audit", "at": e.ts, "seq": e.seq, "actor": e.actor, "role": e.role,
            "action": e.action, "payload": e.payload,
        }))
    for d in db.execute(
        select(Decision).where(Decision.fund_id == fund.id, Decision.case_id == case_id).order_by(Decision.id)
    ).scalars():
        at = d.created_at.astimezone(timezone.utc)
        events.append((at.replace(microsecond=0), 1, d.id, {
            "type": "decision", "at": at.isoformat(timespec="seconds"), "decision_id": d.id,
            "user": _username(db, d.user_id, names), "role": d.role, "decision": d.decision,
            "category": d.category, "final_category": d.final_category, "note": d.note,
            "case_version": d.case_version,
            "voided_at": d.voided_at.isoformat(timespec="seconds") if d.voided_at else None,
            "void_reason": d.void_reason,
        }))
    events.sort(key=lambda e: e[:3])
    return [e[3] for e in events]


def case_days(db: Session, fund: Fund, case_id: str) -> list[dict[str, Any]]:
    """The case at the end of every day it was in a run (its ledger snapshots), oldest first.

    ``cause`` is the cause a person read off the case that day (``ledger.current_category``:
    resolved, else reclassified, else the accepted AI cause, else the rules'); ``category``
    is the rules' cause; ``is_open`` is false on the day it cleared.
    """
    rows = db.execute(
        select(CaseSnapshot.as_of, CaseSnapshot.is_open, CaseSnapshot.data, BusinessDay.status)
        .join(BusinessDay, BusinessDay.id == CaseSnapshot.business_day_id)
        .where(CaseSnapshot.fund_id == fund.id, CaseSnapshot.case_id == case_id)
        .order_by(CaseSnapshot.as_of)
    ).all()
    out = []
    for as_of, is_open, data, day_status in rows:
        case = case_from_dict(data)
        out.append({
            "as_of": str(as_of),
            "day_status": day_status,
            "is_open": is_open,
            "status": case.status,
            "cause": current_category(case).value,
            "category": case.category.value,
            "age_days": case.age_days,
            "nav_impact": case.nav_impact,
            "nav_impact_bp": case.nav_impact_bp,
            "material": case.material,
            "escalated": case.escalated,
            "sla_breached": case.sla_breached,
            "reviewed_by": case.reviewed_by or None,
        })
    return out


def case_evidence(db: Session, fund: Fund, day: BusinessDay, case: Case) -> dict[str, Any]:
    """The breaks and the stored-file records behind a case on ``day``."""
    break_rows = db.execute(
        select(BreakRow).where(BreakRow.business_day_id == day.id).order_by(BreakRow.id)
    ).scalars().all()
    ids = set(case.break_ids)
    mine = [b for b in break_rows if b.case_id == case.case_id or b.break_id in ids]
    references = {b.reference for b in mine if b.reference}

    data = load_day_data(db, day)
    sid = case.security_id

    def related(security_id: str, reference: str = "") -> bool:
        return bool(sid) and security_id == sid or bool(reference) and reference in references

    security = data.securities.get(sid)
    position = data.book_positions.get(sid)
    holding = data.custodian_holdings.get(sid)
    carried: list[dict[str, Any]] = []
    prev = previous_business_day(fund, day.as_of)
    if prev is not None:
        prev_day = get_day(db, fund, prev)
        if prev_day is not None:
            for item in db.execute(
                select(OpenItem).where(OpenItem.business_day_id == prev_day.id).order_by(OpenItem.id)
            ).scalars():
                if related(item.security_id, item.reference):
                    carried.append({"side": item.side, **{k: v for k, v in item.data.items() if k != "position"}})
    return {
        "security": _plain(security) if security else None,
        "breaks": [
            {"break_id": b.break_id, "kind": b.kind, "security_id": b.security_id, "book_value": b.book_value,
             "custodian_value": b.custodian_value, "difference": b.difference, "reference": b.reference,
             "note": b.note}
            for b in mine
        ],
        "book_position": _plain(position) if position else None,
        "custodian_holding": _plain(holding) if holding else None,
        "book_trades": [trade_to_dict(t) for t in data.book_trades if related(t.security_id, t.trade_id)],
        "book_cash": [_plain(e) for e in data.book_cash if related(e.security_id, e.reference)],
        "custodian_cash": [cash_line_to_dict(line) for line in data.custodian_cash
                           if related(line.security_id, line.reference)],
        "carried_items": carried,
        "fx_rate": data.fx_rates.get(security.currency) if security else None,
    }


# --------------------------------------------------------------------------- deciding


def _store_decided_case(db: Session, fund: Fund, row: CaseRow, case: Case) -> None:
    """Write a decided case to its row (bumping ``version``) and to the day's ledger snapshot."""
    for key, value in _case_columns(case).items():
        setattr(row, key, value)
    row.version = row.version + 1
    snap = db.get(CaseSnapshot, (fund.id, case.case_id, row.last_as_of), with_for_update=True)
    if snap is not None:
        snap.status = case.status
        snap.category = case.category.value
        snap.data = case_to_dict(case)


def decide(
    db: Session,
    fund: Fund,
    case_id: str,
    user: User,
    decision: str,
    version: int,
    note: str = "",
    category: str | None = None,
) -> CaseRow:
    """Apply one decision in ``db``'s transaction (the caller commits); ``HTTPException`` on refusal."""
    note = (note or "").strip()
    if decision == "reject" and not note:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A rejection needs a note explaining why.")
    final: Category | None = None
    if decision == "reclassify":
        try:
            final = Category((category or "").strip().upper())
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Reclassify needs a cause, one of: {', '.join(c.value for c in Category)}.",
            ) from None

    peek = db.execute(
        select(CaseRow.last_as_of).where(CaseRow.fund_id == fund.id, CaseRow.case_id == case_id)
    ).scalar_one_or_none()
    if peek is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No case {case_id} in {fund.code}.")
    # Lock the day, then the case: the order the runner and sign-off take them in.
    day = get_day(db, fund, peek, for_update=True)
    row = db.get(CaseRow, (fund.id, case_id), with_for_update=True, populate_existing=True)
    if row is None or day is None or row.last_as_of != day.as_of:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{case_id} changed while the decision was made; reload it.")
    if day.status == "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{day.as_of} is signed off; its cases are locked.")
    if day.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{day.as_of} is {day.status}; cases can be decided once its run is ready.")
    if row.cleared_on is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{case_id} cleared on {row.cleared_on}; nothing to decide.")
    if row.version != version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{case_id} was changed by someone else (version {row.version}, you had {version}); reload it.",
        )

    case = case_from_dict(row.data)
    audit = DbAuditLog(db, fund_id=fund.id)
    review = ReviewSession([case], audit, user.username, user.role)
    try:
        if decision == "approve":
            review.approve(case_id, note)
        elif decision == "reject":
            review.reject(case_id, note)
        else:
            review.reclassify(case_id, final, note)
    except PermissionDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ReviewError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    db.add(Decision(
        fund_id=fund.id, case_id=case_id, business_day_id=day.id, user_id=user.id, role=user.role,
        decision=decision, category=case.category.value, final_category=_cat(case.final_category), note=note,
        case_version=version,
    ))
    _store_decided_case(db, fund, row, case)
    db.flush()
    return row


def case_detail(db: Session, fund: Fund, row: CaseRow, case: Case, day: BusinessDay) -> dict[str, Any]:
    evidence = case_evidence(db, fund, day, case)
    name = (evidence["security"] or {}).get("name", "")
    return {
        **case_item(case, row.version, name),
        "as_of": str(day.as_of),
        "day_status": day.status,
        "is_open": not case.cleared_on,
        "case": case_to_dict(case),
        **evidence,
        "history": case_history(db, fund, case.case_id),
        "days": case_days(db, fund, case.case_id),
    }


# --------------------------------------------------------------------------- routes

router = APIRouter(prefix="/api/funds/{code}", tags=["cases"])


@router.get("/days/{as_of}/cases")
def case_queue(
    code: str,
    as_of: str,
    status_: str | None = Query(None, alias="status"),
    category: str | None = None,
    material: bool | None = None,
    escalated: bool | None = None,
    sla: bool | None = None,
    age: str | None = None,
    ai_disagrees: bool | None = None,
    q: str | None = Query(None, max_length=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """The day's open cases, largest absolute NAV impact first, filtered as asked."""
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    statuses = _choices(status_, STATUSES, "status")
    categories = _choices(category, tuple(c.value for c in Category), "category")
    ages = None
    if age is not None and age.strip():
        ages = {a.strip() for a in age.split(",") if a.strip()}
        if ages - set(BUCKETS):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Unknown age bucket. Allowed: {', '.join(BUCKETS)}.")
    day = require_run_day(db, fund, day_date)
    cases = open_cases_for_day(db, fund, day_date)
    versions = case_versions(db, fund, [c.case_id for c in cases])
    names = _security_names(load_day_data(db, day)) if cases else {}
    items = [case_item(c, versions.get(c.case_id), names.get(c.security_id, "")) for c in cases]
    return filter_cases(items, statuses=statuses, categories=categories, material=material, escalated=escalated,
                        sla=sla, age=ages, ai_disagrees=ai_disagrees, q=q)


@router.get("/cases/{case_id}")
def read_case(
    code: str,
    case_id: str,
    as_of: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """A case with its evidence and history, as it stood at the end of ``as_of`` (default: its latest day)."""
    fund = get_fund(db, code)
    row = db.get(CaseRow, (fund.id, case_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No case {case_id} in {fund.code}.")
    day_date = parse_as_of(as_of) if as_of else row.last_as_of
    snap = db.get(CaseSnapshot, (fund.id, case_id, day_date))
    if snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{case_id} was not in the run for {day_date}.")
    day = require_run_day(db, fund, day_date)
    return case_detail(db, fund, row, case_from_dict(snap.data), day)


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "reclassify"]
    category: str | None = Field(None, max_length=32)
    note: str = Field("", max_length=MAX_NOTE_LENGTH)
    version: int


@router.post("/cases/{case_id}/decision")
def post_decision(
    code: str,
    case_id: str,
    body: DecisionRequest,
    user: User = Depends(require_roles("analyst", "approver")),
    db: Session = Depends(get_db),
) -> dict:
    """Approve, reject or reclassify a case (see module doc); answers with the updated case."""
    fund = get_fund(db, code)
    row = decide(db, fund, case_id, user, body.decision, body.version, body.note, body.category)
    db.commit()
    day = get_day(db, fund, row.last_as_of)
    return case_detail(db, fund, row, case_from_dict(row.data), day)
