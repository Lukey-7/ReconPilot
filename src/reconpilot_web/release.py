"""One release status for a day, sign-off with four-eyes, and day locking (spec 9).

The release status is computed on the server from the day's current cases and
its checks, and is the same for everyone who asks: *ready*, or *blocked* with
every reason. Reasons, with the cases behind each:

``NOT_RUN``                   the day has no finished run (or is being run again)
``PENDING_DECISIONS``         open cases nobody has decided yet
``MATERIAL_NOT_APPROVED``     material cases not approved or reclassified (the engine's rule)
``ESCALATED_NEEDS_APPROVER``  escalated cases not decided by an approver
``CHECK_FAILED``              a release check that failed (one reason per check)

The engine's own ``NAV release`` check covers material cases only, so it is not
a separate failure here (``MATERIAL_NOT_APPROVED`` says the same thing from the
live cases) and is shown to clients under its accurate name, ``Material cases
approved``, recomputed from the current cases so it never contradicts the status.

On top of that, ``can_sign_off`` adds ``FOUR_EYES`` for a person who decided any
of the day's open cases: whoever signs off must not have decided any of them.

Sign-off (approvers only) locks the day row, re-checks everything inside that
transaction, then calls the engine's ``ReviewSession.sign_off``, which writes
``DAY_SIGNED_OFF``. A refused sign-off is audited as ``SIGN_OFF_BLOCKED`` and
answered with 409 and the reasons. A signed-off day is locked: its files, run and
cases can no longer change, and the next business day can be loaded.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reconpilot.impact import blocking_cases, release_check
from reconpilot.models import Case
from reconpilot.nav import FAIL
from reconpilot.review import PermissionDenied, ReviewError, ReviewSession
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import current_user, get_db, require_roles
from reconpilot_web.cases import open_cases_for_day
from reconpilot_web.days import day_payload, get_day, parse_as_of
from reconpilot_web.funds import fund_settings, get_fund
from reconpilot_web.models import BusinessDay, Decision, Fund, User

ENGINE_RELEASE_CHECK = "NAV release"
RELEASE_CHECK_NAME = "Material cases approved"

NOT_RUN = "NOT_RUN"
PENDING_DECISIONS = "PENDING_DECISIONS"
MATERIAL_NOT_APPROVED = "MATERIAL_NOT_APPROVED"
ESCALATED_NEEDS_APPROVER = "ESCALATED_NEEDS_APPROVER"
CHECK_FAILED = "CHECK_FAILED"
FOUR_EYES = "FOUR_EYES"
REASON_CODES = (NOT_RUN, PENDING_DECISIONS, MATERIAL_NOT_APPROVED, ESCALATED_NEEDS_APPROVER, CHECK_FAILED,
                FOUR_EYES)


@dataclass
class Reason:
    code: str
    message: str
    case_ids: list[str] = field(default_factory=list)


@dataclass
class ReleaseStatus:
    ready: bool
    reasons: list[Reason] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "reasons": [asdict(r) for r in self.reasons]}


def _ids(cases: list[Case]) -> list[str]:
    return [c.case_id for c in cases]


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def escalated_needing_approver(cases: list[Case]) -> list[Case]:
    """Open escalated cases whose decision (if any) was not an approver's (the engine's rule)."""
    return [c for c in cases if c.escalated and not c.cleared_on and c.reviewed_role != "approver"]


def compute_release(day_row: BusinessDay | None, cases: list[Case], checks: list[dict]) -> ReleaseStatus:
    """The day's release status from its open ``cases`` and its run's ``checks``."""
    if day_row is None or day_row.run_at is None or day_row.status not in ("ready", "signed_off"):
        state = "has no files" if day_row is None else {
            "running": "is being run", "failed": "failed its last run",
        }.get(day_row.status, "has not been run")
        return ReleaseStatus(False, [Reason(NOT_RUN, f"The day {state}.")])
    reasons: list[Reason] = []
    open_cases = [c for c in cases if not c.cleared_on]
    pending = [c for c in open_cases if c.status == "PENDING"]
    if pending:
        reasons.append(Reason(PENDING_DECISIONS, f"{_plural(len(pending), 'case')} still pending a decision.",
                              _ids(pending)))
    material = blocking_cases(open_cases)
    if material:
        reasons.append(Reason(MATERIAL_NOT_APPROVED,
                              f"{_plural(len(material), 'material case')} not approved or reclassified.",
                              _ids(material)))
    escalated = escalated_needing_approver(open_cases)
    if escalated:
        reasons.append(Reason(ESCALATED_NEEDS_APPROVER,
                              f"{_plural(len(escalated), 'escalated case')} {'needs' if len(escalated) == 1 else 'need'} "
                              "a decision by an approver.",
                              _ids(escalated)))
    for check in checks or []:
        if check.get("status") == FAIL and check.get("name") != ENGINE_RELEASE_CHECK:
            reasons.append(Reason(CHECK_FAILED, f"{check.get('name')} failed: {check.get('detail', '')}".strip()))
    return ReleaseStatus(not reasons, reasons)


def can_sign_off(
    status_: ReleaseStatus,
    cases: list[Case],
    user: User,
    *,
    decided_case_ids: Collection[str] = (),
) -> list[Reason]:
    """The reasons ``user`` cannot sign off: the day's reasons plus ``FOUR_EYES``.

    Four-eyes applies when the user decided any open case for the day: the case's
    current decision is theirs (the engine's rule), or ``decided_case_ids`` (their
    non-voided decisions recorded for the day) names it.
    """
    reasons = list(status_.reasons)
    decided = set(decided_case_ids)
    own = [c.case_id for c in cases if not c.cleared_on and (c.reviewed_by == user.username or c.case_id in decided)]
    if own:
        reasons.append(Reason(FOUR_EYES, f"You decided {_plural(len(own), 'case')} today, so another approver "
                                         f"must sign off.", own))
    return reasons


def client_checks(checks: list[dict] | None, cases: list[Case], materiality_bp: float) -> list[dict]:
    """The run's checks for clients: the engine's ``NAV release`` renamed and recomputed from ``cases``."""
    out = []
    for check in checks or []:
        if check.get("name") == ENGINE_RELEASE_CHECK:
            live = release_check([c for c in cases if not c.cleared_on], materiality_bp)
            out.append({**check, "name": RELEASE_CHECK_NAME, "status": live.status, "detail": live.detail})
        else:
            out.append(dict(check))
    return out


# --------------------------------------------------------------------------- loading


def day_cases(db: Session, fund: Fund, day: BusinessDay | None) -> list[Case]:
    return open_cases_for_day(db, fund, day.as_of) if day is not None and day.run_at is not None else []


def decided_today(db: Session, day: BusinessDay | None, user: User) -> set[str]:
    """Cases ``user`` decided on ``day`` (decisions not voided by a re-run)."""
    if day is None:
        return set()
    return set(db.execute(
        select(Decision.case_id).where(
            Decision.business_day_id == day.id, Decision.user_id == user.id, Decision.voided_at.is_(None))
    ).scalars())


def release_payload(db: Session, fund: Fund, day: BusinessDay | None, as_of: date, user: User) -> dict[str, Any]:
    cases = day_cases(db, fund, day)
    status_ = compute_release(day, cases, day.checks if day is not None else [])
    blocking = can_sign_off(status_, cases, user, decided_case_ids=decided_today(db, day, user))
    signed_off = day is not None and day.status == "signed_off"
    return {
        "fund": fund.code,
        "as_of": str(as_of),
        "day_status": day.status if day is not None else None,
        "signed_off": signed_off,
        **status_.to_dict(),
        "checks": client_checks(day.checks if day is not None else [], cases,
                                float(fund_settings(fund)["materiality_bp"])),
        "signable_by_me": user.role == "approver" and not signed_off and not blocking,
        "blocking_for_me": [asdict(r) for r in blocking],
    }


# --------------------------------------------------------------------------- routes

router = APIRouter(prefix="/api/funds/{code}/days", tags=["release"])


@router.get("/{as_of}/release")
def read_release(
    code: str,
    as_of: str,
    for_user: str | None = Query(None, pattern="^me$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """The day's release status (the same for everyone) and whether the caller could sign off."""
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    return release_payload(db, fund, get_day(db, fund, day_date), day_date, user)


class SignOffRefused(Exception):
    """Sign-off refused; ``detail`` is the 409 body. The refusal's audit entry is already written."""

    def __init__(self, detail: dict[str, Any]):
        super().__init__(detail.get("message", ""))
        self.detail = detail


def sign_off_day(db: Session, fund: Fund, day_date: date, user: User) -> BusinessDay:
    """Sign off the day as ``user`` in ``db``'s transaction (the caller commits).

    Re-checks everything under the day's lock. 404 or 409 (``HTTPException``) when there is
    no day or it is already signed off; ``SignOffRefused`` when a reason blocks it, after
    auditing ``SIGN_OFF_BLOCKED`` (the caller commits that entry before answering 409).
    """
    day = get_day(db, fund, day_date, for_update=True)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {day_date}.")
    if day.status == "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{day_date} is already signed off.")

    cases = day_cases(db, fund, day)
    status_ = compute_release(day, cases, day.checks or [])
    reasons = can_sign_off(status_, cases, user, decided_case_ids=decided_today(db, day, user))
    audit = DbAuditLog(db, fund_id=fund.id)
    if reasons:
        audit.append(user.username, user.role, "SIGN_OFF_BLOCKED", {
            "as_of": str(day_date),
            "reasons": [{"code": r.code, "cases": r.case_ids} for r in reasons],
        })
        raise SignOffRefused({
            "message": f"{day_date} cannot be signed off yet.",
            "reasons": [asdict(r) for r in reasons],
        })

    try:
        ReviewSession(cases, audit, user.username, user.role).sign_off()
    except (PermissionDenied, ReviewError) as exc:  # the engine's own rules, as a second line of defence
        raise SignOffRefused({"message": str(exc), "reasons": []}) from None  # keeps the engine's entry

    day.status = "signed_off"
    day.signed_off_by = user.id
    day.signed_off_at = func.now()
    day.release_ready = True
    day.release = {**status_.to_dict(), "signed_off_by": user.username}
    return day


@router.post("/{as_of}/signoff")
def sign_off(
    code: str,
    as_of: str,
    user: User = Depends(require_roles("approver")),
    db: Session = Depends(get_db),
) -> dict:
    """Sign off the day (see module doc): 200 with the signed-off day, or 409 with the reasons."""
    fund = get_fund(db, code)
    try:
        day = sign_off_day(db, fund, parse_as_of(as_of), user)
    except SignOffRefused as refused:
        db.commit()  # keep the SIGN_OFF_BLOCKED entry
        raise HTTPException(status.HTTP_409_CONFLICT, refused.detail) from None
    db.commit()
    db.refresh(day)
    return day_payload(db, fund, day)
