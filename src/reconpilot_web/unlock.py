"""Unlocking a signed-off day (spec section 9, owner's decision): two people, with a reason.

Sign-off locks a day. Occasionally a locked day must be reopened (a price corrected after
release, a decision recorded against the wrong cause). Here that takes two people:

1. An **administrator** asks, with a reason (``UNLOCK_REQUESTED``).
2. A **different** user with the **approver** role confirms within 24 hours
   (``DAY_UNLOCKED``), or declines with a note (``UNLOCK_DECLINED``). The requester may
   withdraw the request (``UNLOCK_WITHDRAWN``). A request nobody confirmed in 24 hours
   expires (``UNLOCK_EXPIRED``, written the next time anyone acts on the day's requests).

Only the fund's **latest signed-off day** can be unlocked, and only **before the next
business day has run** (once it has, its cases were carried from this day's sign-off).
Both are checked when asking and again, under the day's lock, when confirming. One
request may be pending per day.

Confirming returns the day to ``ready``: its sign-off is cleared, its cases can be decided
again, and it must be signed off again (with four-eyes) before the next day can be loaded
or run. Nothing else changes: the files, the run and every decision stand, and the audit
log keeps the original sign-off.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import SYSTEM_ACTOR, SYSTEM_ROLE, current_user, get_db
from reconpilot_web.days import get_day, next_business_day, parse_as_of
from reconpilot_web.funds import get_fund
from reconpilot_web.models import BusinessDay, Fund, UnlockRequest, User

CONFIRM_WITHIN = timedelta(hours=24)
# A day in one of these has been run (or is being run): too late to unlock the day before it.
RUN_STARTED = ("running", "ready", "signed_off", "failed")

router = APIRouter(prefix="/api/funds/{code}/days", tags=["unlock"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _username(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user.username if user is not None else None


# --------------------------------------------------------------------------- rules


def unlock_problem(db: Session, fund: Fund, day: BusinessDay | None) -> str | None:
    """Why the day cannot be unlocked now, or ``None`` if it can (signed off, latest, next day not run)."""
    if day is None:
        return "No files have been loaded for this day."
    if day.status != "signed_off":
        return f"{day.as_of} is not signed off, so there is nothing to unlock."
    later = db.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of > day.as_of)
        .order_by(BusinessDay.as_of)
    ).scalars().all()
    for row in later:
        if row.status == "signed_off":
            return f"Only the latest signed-off day can be unlocked; {row.as_of} is signed off too."
    for row in later:
        if row.status in RUN_STARTED or row.run_at is not None:
            return (f"{row.as_of} has already been run from this day's sign-off; "
                    "a day can be unlocked only before the next day runs.")
    return None


def expire_stale(db: Session, fund: Fund, now: datetime) -> None:
    """Mark the fund's pending requests older than 24 hours ``expired``, each with an audit entry."""
    stale = db.execute(
        select(UnlockRequest).where(
            UnlockRequest.fund_id == fund.id, UnlockRequest.status == "pending", UnlockRequest.expires_at <= now)
        .with_for_update()
    ).scalars().all()
    if not stale:
        return
    audit = DbAuditLog(db, fund_id=fund.id)
    for req in stale:
        req.status = "expired"
        req.decided_at = now
        day = db.get(BusinessDay, req.business_day_id)
        audit.append(SYSTEM_ACTOR, SYSTEM_ROLE, "UNLOCK_EXPIRED", {
            "as_of": str(day.as_of) if day else None, "request_id": req.id,
            "requested_by": _username(db, req.requested_by),
        })
    db.flush()


def _status(req: UnlockRequest, now: datetime) -> str:
    """The request's status as it stands now: a pending request past its expiry reads as expired."""
    return "expired" if req.status == "pending" and req.expires_at <= now else req.status


def request_payload(db: Session, req: UnlockRequest, user: User, now: datetime) -> dict[str, Any]:
    current = _status(req, now)
    mine = req.requested_by == user.id
    pending = current == "pending"
    return {
        "id": req.id,
        "status": current,
        "reason": req.reason,
        "requested_by": _username(db, req.requested_by),
        "requested_at": req.requested_at.isoformat(),
        "expires_at": req.expires_at.isoformat(),
        "decided_by": _username(db, req.decided_by),
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
        "decision_note": req.decision_note,
        "confirmable_by_me": pending and not mine and user.role == "approver",
        "declinable_by_me": pending and not mine and user.role == "approver",
        "withdrawable_by_me": pending and mine,
    }


def unlock_payload(db: Session, fund: Fund, day: BusinessDay, user: User) -> dict[str, Any]:
    """The day's unlock state for ``user``: whether it can be unlocked, the pending request, the history."""
    now = _now()
    problem = unlock_problem(db, fund, day)
    rows = db.execute(
        select(UnlockRequest).where(UnlockRequest.business_day_id == day.id).order_by(UnlockRequest.id.desc())
    ).scalars().all()
    requests = [request_payload(db, r, user, now) for r in rows]
    pending = next((r for r in requests if r["status"] == "pending"), None)
    return {
        "fund": fund.code,
        "as_of": str(day.as_of),
        "day_status": day.status,
        "signed_off_by": _username(db, day.signed_off_by),
        "signed_off_at": day.signed_off_at.isoformat() if day.signed_off_at else None,
        "unlockable": problem is None,
        "problem": problem,
        "requestable_by_me": problem is None and pending is None and user.is_admin,
        "pending": pending,
        "history": [r for r in requests if r is not pending],
        "confirm_within_hours": int(CONFIRM_WITHIN.total_seconds() // 3600),
    }


def _day(db: Session, fund: Fund, as_of: str, *, for_update: bool = False) -> BusinessDay:
    day_date: date = parse_as_of(as_of)
    day = get_day(db, fund, day_date, for_update=for_update)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {day_date}.")
    return day


def _request(db: Session, day: BusinessDay, request_id: int) -> UnlockRequest:
    req = db.get(UnlockRequest, request_id, with_for_update=True, populate_existing=True)
    if req is None or req.business_day_id != day.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No unlock request {request_id} for {day.as_of}.")
    return req


def _require_pending(db: Session, req: UnlockRequest, now: datetime) -> None:
    """409 unless the request is still pending (committing any expiry entries first)."""
    current = _status(req, now)
    if current != "pending":
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, f"This unlock request is {current}; ask again if still needed.")


# --------------------------------------------------------------------------- routes


class UnlockAsk(BaseModel):
    reason: str = Field(max_length=2000)


class UnlockAnswer(BaseModel):
    note: str = Field("", max_length=2000)


@router.get("/{as_of}/unlock")
def read_unlock(code: str, as_of: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Whether the day can be unlocked, the pending request (with what the caller may do) and past requests."""
    fund = get_fund(db, code)
    return unlock_payload(db, fund, _day(db, fund, as_of), user)


@router.post("/{as_of}/unlock", status_code=status.HTTP_201_CREATED)
def ask_unlock(code: str, as_of: str, body: UnlockAsk, user: User = Depends(current_user),
               db: Session = Depends(get_db)) -> dict:
    """An administrator asks to unlock the day, with a reason; a different approver must confirm."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an administrator can ask to unlock a day.")
    reason = body.reason.strip()
    if len(reason) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Give the reason for unlocking in a sentence (at least 10 characters).")
    fund = get_fund(db, code)
    now = _now()
    day = _day(db, fund, as_of, for_update=True)
    expire_stale(db, fund, now)
    problem = unlock_problem(db, fund, day)
    if problem is not None:
        db.commit()  # keep any expiry entries
        raise HTTPException(status.HTTP_409_CONFLICT, problem)
    pending = db.execute(
        select(UnlockRequest.id).where(UnlockRequest.business_day_id == day.id, UnlockRequest.status == "pending")
    ).first()
    if pending is not None:
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, f"An unlock of {day.as_of} is already waiting for an approver.")
    req = UnlockRequest(fund_id=fund.id, business_day_id=day.id, reason=reason, status="pending",
                        requested_by=user.id, requested_at=now, expires_at=now + CONFIRM_WITHIN)
    db.add(req)
    db.flush()
    DbAuditLog(db, fund_id=fund.id).append(user.username, user.role, "UNLOCK_REQUESTED", {
        "as_of": str(day.as_of), "request_id": req.id, "reason": reason, "expires_at": req.expires_at.isoformat(),
    })
    db.commit()
    return unlock_payload(db, fund, day, user)


@router.post("/{as_of}/unlock/{request_id}/confirm")
def confirm_unlock(code: str, as_of: str, request_id: int, body: UnlockAnswer, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict:
    """A different approver confirms: the day returns to ``ready`` and must be signed off again."""
    fund = get_fund(db, code)
    now = _now()
    day = _day(db, fund, as_of, for_update=True)
    req = _request(db, day, request_id)
    if user.role != "approver":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an approver can confirm an unlock.")
    if req.requested_by == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "You asked for this unlock; a different approver must confirm it (four-eyes).")
    expire_stale(db, fund, now)
    _require_pending(db, req, now)
    problem = unlock_problem(db, fund, day)
    if problem is not None:
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, problem)

    previous_by, previous_at = _username(db, day.signed_off_by), day.signed_off_at
    req.status = "confirmed"
    req.decided_by = user.id
    req.decided_at = now
    req.decision_note = body.note.strip()
    day.status = "ready"
    day.signed_off_by = None
    day.signed_off_at = None
    day.release_ready = None  # computed from the current cases again
    day.release = None
    DbAuditLog(db, fund_id=fund.id).append(user.username, user.role, "DAY_UNLOCKED", {
        "as_of": str(day.as_of),
        "request_id": req.id,
        "reason": req.reason,
        "requested_by": _username(db, req.requested_by),
        "note": req.decision_note,
        "previously_signed_off_by": previous_by,
        "previously_signed_off_at": previous_at.isoformat() if previous_at else None,
        "next_day": str(next_business_day(fund, day.as_of)),
    })
    db.commit()
    db.refresh(day)
    return unlock_payload(db, fund, day, user)


@router.post("/{as_of}/unlock/{request_id}/decline")
def decline_unlock(code: str, as_of: str, request_id: int, body: UnlockAnswer, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict:
    """The requester withdraws the request, or another approver declines it with a note."""
    fund = get_fund(db, code)
    now = _now()
    day = _day(db, fund, as_of, for_update=True)
    req = _request(db, day, request_id)
    withdraw = req.requested_by == user.id
    if not withdraw and user.role != "approver":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an approver can decline an unlock.")
    note = body.note.strip()
    if not withdraw and not note:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Say why the unlock is declined.")
    expire_stale(db, fund, now)
    _require_pending(db, req, now)
    req.status = "withdrawn" if withdraw else "declined"
    req.decided_by = user.id
    req.decided_at = now
    req.decision_note = note
    DbAuditLog(db, fund_id=fund.id).append(
        user.username, user.role, "UNLOCK_WITHDRAWN" if withdraw else "UNLOCK_DECLINED",
        {"as_of": str(day.as_of), "request_id": req.id, "note": note},
    )
    db.commit()
    return unlock_payload(db, fund, day, user)
