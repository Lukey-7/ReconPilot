"""A business day's audit trail, shown at sign-off (spec sections 8 and 10, screen 4).

``GET /api/funds/{code}/days/{as_of}/audit`` returns the fund's audit entries for
one business day, oldest first, with the result of re-checking the whole hash
chain on the server.

The chain is global and most engine entries (decisions, escalations, AI calls,
sign-off) carry no date, so a day's entries are found by position: days are
worked strictly in order (a day must be signed off before the next one can be
loaded), so the day's trail runs from the fund's first entry about that day
(its first upload) up to, not including, the fund's first entry about a later
day. Inside that window an entry that names a different day (``as_of`` in its
payload) is left out. Entries without a fund (sign-ins) are never part of a day.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from reconpilot_web.auditlog import verify_chain
from reconpilot_web.auth import current_user, get_db
from reconpilot_web.days import get_day, parse_as_of
from reconpilot_web.funds import get_fund
from reconpilot_web.models import AuditEntry, Fund, User


def _entry(e: AuditEntry) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "ts": e.ts,
        "actor": e.actor,
        "role": e.role,
        "action": e.action,
        "case_id": e.case_id,
        "payload": e.payload,
        "prev_hash": e.prev_hash,
        "hash": e.hash,
    }


def day_window(db: Session, fund: Fund, as_of: date) -> list[ColumnElement[bool]] | None:
    """Conditions selecting the fund's audit entries for ``as_of`` (see module doc), or None if it has none."""
    day = str(as_of)
    named = AuditEntry.payload["as_of"].astext
    start = db.execute(
        select(func.min(AuditEntry.seq)).where(AuditEntry.fund_id == fund.id, named == day)
    ).scalar_one_or_none()
    if start is None:
        return None
    end = db.execute(
        select(func.min(AuditEntry.seq)).where(AuditEntry.fund_id == fund.id, AuditEntry.seq > start, named > day)
    ).scalar_one_or_none()
    conditions = [
        AuditEntry.fund_id == fund.id,
        AuditEntry.seq >= start,
        or_(named.is_(None), named == day),
    ]
    if end is not None:
        conditions.append(AuditEntry.seq < end)
    return conditions


def day_entries(db: Session, fund: Fund, as_of: date) -> list[AuditEntry]:
    """The fund's audit entries for ``as_of`` in chain order (see module doc)."""
    conditions = day_window(db, fund, as_of)
    if conditions is None:
        return []
    return list(db.execute(select(AuditEntry).where(*conditions).order_by(AuditEntry.seq)).scalars())


router = APIRouter(prefix="/api/funds/{code}/days", tags=["audit"])


@router.get("/{as_of}/audit")
def read_day_audit(
    code: str,
    as_of: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """The day's audit trail and whether the whole chain still verifies. Any signed-in role."""
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    if get_day(db, fund, day_date) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {day_date}.")
    chain_ok, broken_at = verify_chain(db)
    return {
        "fund": fund.code,
        "as_of": str(day_date),
        "entries": [_entry(e) for e in day_entries(db, fund, day_date)],
        "chain_ok": chain_ok,
        "broken_at": broken_at,
    }
