"""Demo mode (spec section 11): a fund of their own for every visitor, from a fixed seed.

A demo instance is a separate ``reconpilot-web serve --mode demo`` with its own
database (the instance mode guard refuses a real database). Uploads are switched
off on its server. Instead:

**Try the demo** (``POST /api/demo``) makes the visitor a fund by running the
engine's sequence generator from a fixed seed: a hard-mode working week. The week's
files go through the same intake, validation and run code as an upload; the first
four days are then worked by the fund's own sandbox users through the real decision
and sign-off code (the analyst decides the cases, the second approver decides the
escalated ones, the first approver signs off, so four-eyes holds), and the last day
is left waiting for the visitor. The fund comes with four one-click users (an
analyst, two approvers to show four-eyes, and a viewer) who have no password: they
are entered only through this module, which signs the visitor in as the analyst and
lets them switch between the four (``POST /api/demo/switch``). Each sandbox user sees
its own fund and nothing else (``auth.fund_scope``), so nothing is shared between
visitors. The browser also keeps an ``rp_demo`` cookie whose token (stored hashed on
the fund) lets the visitor return to their fund once their session has ended
(``POST /api/demo/resume``), for as long as the fund lives.

**Generate the next business day** (``POST /api/demo/next-day``) takes the next day
of the same generated sequence once the latest day is signed off, stores and
validates its files as an upload would, and queues its run for the worker.

The AI's answers come from a cache built in advance for this seed by running the
real AI (``scripts/build_demo_ai_cache.py``) and loaded into the database when the
instance starts (``aicache.load_demo_cache``); a visitor's fund never calls a
provider, and anything not cached falls back to the rules.

A visitor's fund expires ``auth.DEMO_TTL`` (24 hours) after its last use; the
cleanup job (``delete_expired``, run every ``CLEANUP_INTERVAL`` by the demo server
and by ``reconpilot-web demo-cleanup``) deletes it with its days, cases and users.
Its audit entries stay: the log is append-only. Starting a demo is rate-limited per
visitor address and the number of live demo funds is capped (``Settings``).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import tempfile
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from reconpilot.models import Category
from reconpilot.sequence import SequenceConfig, generate_sequence
from reconpilot.storage import write_day
from reconpilot_web import jobs, runner
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import (
    DEMO_TTL,
    SYSTEM_ACTOR,
    SYSTEM_ROLE,
    current_user,
    demo_payload,
    get_db,
    open_session,
    set_session_cookies,
    user_payload,
)
from reconpilot_web.cases import decide
from reconpilot_web.days import next_business_day, queue_run, store_files
from reconpilot_web.funds import create_fund, latest_day
from reconpilot_web.models import BusinessDay, CaseRow, Fund, Job, User
from reconpilot_web.release import SignOffRefused, day_cases, sign_off_day
from reconpilot_web.security import new_token, token_digest
from reconpilot_web.validation import FILE_KINDS

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- the fixed scenario

DEMO_SEED = 62
DEMO_BREAKS_PER_DAY = 4
DEMO_START = date(2026, 11, 9)  # a Monday
DEMO_WEEK = 5  # business days a new demo fund holds: four signed off, the fifth waiting
DEMO_HORIZON = 10  # business days of the sequence, so a visitor can generate five more
DEMO_FUND_NAME = "Demo Global Equity Fund"
DEMO_SETTINGS: dict[str, Any] = {"ai_enabled": True}  # every other setting is the engine's default

# The fund's one-click users: (name in the username, role, display name). The analyst works the
# cases, the second approver decides the escalated ones and the first signs off (four-eyes).
ANALYST, SIGNER, DECIDER, VIEWER = "priya", "ann", "tom", "vic"
DEMO_TEAM: tuple[tuple[str, str, str], ...] = (
    (ANALYST, "analyst", "Priya Shah"),
    (SIGNER, "approver", "Ann Lee"),
    (DECIDER, "approver", "Tom Reed"),
    (VIEWER, "viewer", "Vic Moss"),
)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to misread
DEMO_LOCK_KEY = 727275  # serialises demo creation, so the cap holds under concurrent visitors
CREATION_WINDOW = timedelta(hours=1)
CLEANUP_INTERVAL = timedelta(minutes=10)
RESUME_COOKIE = "rp_demo"
RESUME_COOKIE_AGE = timedelta(days=7)  # the fund's own expiry decides; the cookie only has to outlast it

NOTES = {
    "approve": "Checked against the custodian statement; the suggested cause holds.",
    "reclassify": "The custodian's records point to a different cause; reclassified.",
    "approver": "Reviewed as approver: cause and NAV impact confirmed.",
}


@dataclass(frozen=True)
class DemoDay:
    as_of: date
    files: dict[str, bytes]  # {kind: bytes}, exactly as ``storage.write_day`` writes them
    truth: dict[str, Category]  # the planted cause live on each security that day


@lru_cache(maxsize=1)
def demo_days() -> tuple[DemoDay, ...]:
    """Every business day of the demo's sequence (the same bytes every time)."""
    out = []
    sequence = generate_sequence(DEMO_START, DEMO_HORIZON, DEMO_BREAKS_PER_DAY, DEMO_SEED,
                                 SequenceConfig(difficulty="hard"))
    with tempfile.TemporaryDirectory(prefix="reconpilot_demo_") as tmp:
        for day, truth in sequence:
            folder = write_day(day, Path(tmp) / str(day.as_of))
            files = {kind: (folder / name).read_bytes() for kind, name in FILE_KINDS.items()
                     if (folder / name).is_file()}
            out.append(DemoDay(day.as_of, files, {p.security_id: p.category for p in truth}))
    return tuple(out)


def demo_day(as_of: date) -> DemoDay | None:
    return next((d for d in demo_days() if d.as_of == as_of), None)


class DemoUnavailable(Exception):
    """A demo cannot be started now: ``status_code`` 429 (too many from one visitor) or 503 (full)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# --------------------------------------------------------------------------- building a fund


def visitor_key(ip: str | None, salt: str) -> str:
    """Who is starting a demo, for the rate limit: a salted hash of their address, never the address."""
    return "ip:" + hashlib.sha256(f"{salt}|{ip or 'unknown'}".encode()).hexdigest()[:40]


def new_fund_code(db: Session) -> str:
    while True:
        code = "DEMO-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if db.execute(select(Fund.id).where(Fund.code == code)).first() is None:
            return code


def _create_team(db: Session, fund: Fund) -> dict[str, User]:
    """The fund's one-click users. No password: they are entered only through the demo routes."""
    suffix = fund.code.split("-", 1)[-1].lower()
    audit = DbAuditLog(db, fund_id=fund.id)
    team = {}
    for name, role, display_name in DEMO_TEAM:
        user = User(username=f"{name}.{suffix}", display_name=display_name, password_hash=None, role=role,
                    demo_fund_id=fund.id)
        db.add(user)
        db.flush()
        audit.append(SYSTEM_ACTOR, SYSTEM_ROLE, "USER_CREATED",
                     {"username": user.username, "role": role, "is_admin": False, "demo": True})
        team[name] = user
    return team


def load_demo_day(db: Session, fund: Fund, day: DemoDay, user: User) -> BusinessDay:
    """Store and validate a generated day's files as ``user`` (the upload's own code)."""
    names = {kind: FILE_KINDS[kind] for kind in day.files}
    business_day, report = store_files(db, fund, day.as_of, day.files, names, user, generated=True)
    if not report.ok:  # the generator's files always validate; anything else is a bug
        raise RuntimeError(f"generated files for {day.as_of} did not validate: {report.to_dict()}")
    return business_day


def run_inline(db: Session, fund: Fund, as_of: date, user: User) -> dict:
    """Queue the day's run and run it at once in ``db``'s transaction, as the worker would."""
    job_id = queue_run(db, fund, as_of, user)
    job = db.get(Job, job_id)
    job.status, job.attempts, job.locked_by, job.started_at = "running", 1, "demo-setup", func.clock_timestamp()
    db.flush()
    day = db.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of == as_of)
    ).scalar_one()
    result = runner.run_day_job(db, {"business_day_id": day.id, "user_id": user.id})
    jobs.complete(db, job_id, result)
    job.finished_at = func.clock_timestamp()
    db.flush()
    return result


def review_day(db: Session, fund: Fund, day: DemoDay, team: dict[str, User]) -> int:
    """Work the day's open cases as the sandbox users would, through the real decision code.

    Every case pending a decision is decided by the analyst, and every escalated case
    without an approver's decision by the second approver: approved when the suggested
    cause is the one planted, otherwise reclassified to it (as an analyst would after
    the custodian's reply). Returns how many decisions were taken.
    """
    row_day = db.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of == day.as_of)
    ).scalar_one()
    taken = 0
    for case in day_cases(db, fund, row_day):
        if case.cleared_on:
            continue
        needs_approver = case.escalated and case.reviewed_role != "approver"
        if case.status != "PENDING" and not needs_approver:
            continue
        user = team[DECIDER] if case.escalated else team[ANALYST]
        planted = day.truth.get(case.security_id)
        version = db.execute(
            select(CaseRow.version).where(CaseRow.fund_id == fund.id, CaseRow.case_id == case.case_id)
        ).scalar_one()
        if planted is None or planted is case.category:
            note = NOTES["approver"] if user.role == "approver" else NOTES["approve"]
            decide(db, fund, case.case_id, user, "approve", version, note)
        else:
            decide(db, fund, case.case_id, user, "reclassify", version, NOTES["reclassify"], planted.value)
        taken += 1
    return taken


def create_demo_fund(db: Session, visitor: str, *, max_funds: int, per_hour: int,
                     now: datetime | None = None, resume_hash: str | None = None) -> tuple[Fund, dict[str, User]]:
    """Make a visitor's demo fund with its week of days and its four users (see module doc).

    In ``db``'s transaction (the caller commits). Raises ``DemoUnavailable`` when the
    visitor has started ``per_hour`` demos in the last hour, or ``max_funds`` demo funds
    are live (after deleting any that have expired).
    """
    now = now or datetime.now(timezone.utc)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DEMO_LOCK_KEY})
    delete_expired(db, now)
    recent = db.execute(
        select(func.count(Fund.id)).where(
            Fund.is_demo.is_(True), Fund.demo_visitor == visitor, Fund.created_at > now - CREATION_WINDOW)
    ).scalar_one()
    if recent >= per_hour:
        raise DemoUnavailable(status.HTTP_429_TOO_MANY_REQUESTS,
                              f"You have started {recent} demos in the last hour. Carry on with your latest one, "
                              "or try again later.")
    live = db.execute(select(func.count(Fund.id)).where(Fund.is_demo.is_(True))).scalar_one()
    if live >= max_funds:
        raise DemoUnavailable(status.HTTP_503_SERVICE_UNAVAILABLE,
                              "The demo is full right now. Please try again in a little while.")

    fund = create_fund(db, new_fund_code(db), DEMO_FUND_NAME, DEMO_START, settings=DEMO_SETTINGS)
    fund.is_demo = True
    fund.demo_visitor = visitor
    fund.demo_expires_at = now + DEMO_TTL
    fund.demo_resume_hash = resume_hash
    team = _create_team(db, fund)
    week = demo_days()[:DEMO_WEEK]
    for i, day in enumerate(week):
        load_demo_day(db, fund, day, team[ANALYST])
        run_inline(db, fund, day.as_of, team[ANALYST])
        if i == len(week) - 1:
            break  # the last day waits for the visitor
        review_day(db, fund, day, team)
        try:
            sign_off_day(db, fund, day.as_of, team[SIGNER])
        except SignOffRefused as refused:  # the scenario is fixed, so this is a bug
            raise RuntimeError(f"the demo could not sign off {day.as_of}: {refused.detail}") from None
    DbAuditLog(db, fund_id=fund.id).append(SYSTEM_ACTOR, SYSTEM_ROLE, "DEMO_FUND_CREATED", {
        "code": fund.code, "seed": DEMO_SEED, "breaks_per_day": DEMO_BREAKS_PER_DAY,
        "days": [str(d.as_of) for d in week], "signed_off": [str(d.as_of) for d in week[:-1]],
        "expires_at": fund.demo_expires_at.isoformat(),
    })
    db.flush()
    return fund, team


def generate_next_day(db: Session, fund: Fund, user: User) -> tuple[date, int]:
    """Load the next day of the demo's sequence as ``user`` and queue its run; ``(as_of, job_id)``.

    409 unless the latest day is signed off (days are worked in order), and once the
    sequence has no more days. In ``db``'s transaction (the caller commits).
    """
    latest = latest_day(db, fund)
    if latest is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This demo fund has no days yet.")
    if latest.status != "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Sign off {latest.as_of} first: days are worked in order.")
    as_of = next_business_day(fund, latest.as_of)
    day = demo_day(as_of)
    if day is None:
        last = demo_days()[-1].as_of
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"The demo's synthetic data ends on {last}. Start a new demo to begin again.")
    load_demo_day(db, fund, day, user)
    return as_of, queue_run(db, fund, as_of, user)


# --------------------------------------------------------------------------- expiry


def delete_expired(db: Session, now: datetime | None = None) -> list[str]:
    """Delete every demo fund unused for ``DEMO_TTL`` (its days, cases, users and jobs); their codes.

    Each deletion is audited as ``DEMO_FUND_EXPIRED``; the fund's earlier audit entries
    stay, since the log is append-only. In ``db``'s transaction (the caller commits).
    """
    now = now or datetime.now(timezone.utc)
    expired = db.execute(
        select(Fund).where(Fund.is_demo.is_(True), Fund.demo_expires_at < now)
        .order_by(Fund.id).with_for_update(skip_locked=True)
    ).scalars().all()
    codes = []
    for fund in expired:
        day_ids = list(db.execute(select(BusinessDay.id).where(BusinessDay.fund_id == fund.id)).scalars())
        if day_ids:
            db.execute(delete(Job).where(Job.payload["business_day_id"].as_integer().in_(day_ids)))
        DbAuditLog(db, fund_id=fund.id).append(SYSTEM_ACTOR, SYSTEM_ROLE, "DEMO_FUND_EXPIRED", {
            "code": fund.code,
            "expired_at": fund.demo_expires_at.isoformat() if fund.demo_expires_at else None,
        })
        codes.append(fund.code)
        db.execute(delete(Fund).where(Fund.id == fund.id))  # the database cascades the rest
    db.expunge_all()
    return codes


def cleanup_once(session_factory) -> list[str]:
    with session_factory() as session, session.begin():
        return delete_expired(session)


def run_cleanup(session_factory, stop: threading.Event, interval: timedelta = CLEANUP_INTERVAL) -> None:
    """Delete expired demo funds now and every ``interval`` until ``stop`` is set."""
    while not stop.is_set():
        try:
            codes = cleanup_once(session_factory)
            if codes:
                log.info("deleted %d expired demo fund(s): %s", len(codes), ", ".join(codes))
        except Exception:  # noqa: BLE001 - keep cleaning up on the next round
            log.exception("demo cleanup failed")
        stop.wait(interval.total_seconds())


# --------------------------------------------------------------------------- routes

router = APIRouter(tags=["demo"])

_SALT = secrets.token_hex(16)  # per process: the rate limit needs no address kept anywhere


def require_demo(request: Request) -> None:
    """The demo's routes exist only on a demo instance (404 elsewhere)."""
    if request.app.state.settings.mode != "demo":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


def require_demo_user(user: User = Depends(current_user)) -> User:
    if user.demo_fund_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a demo visitor's users can do this.")
    return user


def _me(db: Session, user: User) -> dict[str, Any]:
    return {**user_payload(user), "demo": demo_payload(db, user)}


def resumable_fund(db: Session, token: str | None, now: datetime | None = None) -> Fund | None:
    """The live demo fund the ``rp_demo`` cookie's token belongs to, if any."""
    if not token:
        return None
    now = now or datetime.now(timezone.utc)
    return db.execute(
        select(Fund).where(Fund.is_demo.is_(True), Fund.demo_resume_hash == token_digest(token),
                           Fund.demo_expires_at > now)
    ).scalar_one_or_none()


def _set_resume_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(RESUME_COOKIE, token, max_age=int(RESUME_COOKIE_AGE.total_seconds()), path="/",
                        httponly=True, samesite="lax", secure=request.app.state.settings.cookie_secure)


def _sign_in(db: Session, request: Request, response: Response, user: User, payload: dict) -> None:
    token, csrf = open_session(db, request, user, datetime.now(timezone.utc))
    DbAuditLog(db, fund_id=user.demo_fund_id).append(user.username, user.role, "SIGN_IN", {
        "ip": request.client.host if request.client else None, **payload,
    })
    db.commit()
    set_session_cookies(response, request, token, csrf)


@router.get("/api/instance")
def read_instance(request: Request, db: Session = Depends(get_db)) -> dict:
    """Whether this instance is real or the demo (no sign-in needed: the sign-in page asks).

    On the demo, ``resume`` names the visitor's own fund when their browser can return to it.
    """
    mode = request.app.state.settings.mode
    out: dict[str, Any] = {"mode": mode}
    if mode == "demo":
        fund = resumable_fund(db, request.cookies.get(RESUME_COOKIE))
        out["demo"] = {
            "expires_after_hours": int(DEMO_TTL.total_seconds() // 3600),
            "week": [str(d.as_of) for d in demo_days()[:DEMO_WEEK]],
            "last_day": str(demo_days()[-1].as_of),
            "resume": {"fund": fund.code, "expires_at": fund.demo_expires_at.isoformat()} if fund else None,
        }
    return out


class StartDemo(BaseModel):
    """Empty: the body exists so the route takes JSON only, which a cross-site form cannot send."""


@router.post("/api/demo", dependencies=[Depends(require_demo)])
def start_demo(body: StartDemo, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    """Make the visitor's demo fund and sign them in as its analyst (see module doc)."""
    settings = request.app.state.settings
    visitor = visitor_key(request.client.host if request.client else None, _SALT)
    resume = new_token()
    try:
        fund, team = create_demo_fund(db, visitor, max_funds=settings.demo_max_funds,
                                      per_hour=settings.demo_creations_per_hour, resume_hash=token_digest(resume))
    except DemoUnavailable as refused:
        db.rollback()
        raise HTTPException(refused.status_code, refused.message) from None
    analyst = team[ANALYST]
    _sign_in(db, request, response, analyst, {"via": "demo"})
    _set_resume_cookie(response, request, resume)
    return {"user": _me(db, analyst), "fund": fund.code}


@router.post("/api/demo/resume", dependencies=[Depends(require_demo)])
def resume_demo(body: StartDemo, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    """Return to the visitor's own fund (from the ``rp_demo`` cookie) as its analyst; 404 once it has gone."""
    token = request.cookies.get(RESUME_COOKIE)
    fund = resumable_fund(db, token)
    if fund is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Your demo fund has expired or is not in this browser. Start a new demo.")
    analyst = db.execute(
        select(User).where(User.demo_fund_id == fund.id, User.role == "analyst").order_by(User.id).limit(1)
    ).scalar_one()
    _sign_in(db, request, response, analyst, {"via": "demo resume"})
    _set_resume_cookie(response, request, token)
    return {"user": _me(db, analyst), "fund": fund.code}


class SwitchUser(BaseModel):
    username: str = Field(..., max_length=64)


@router.post("/api/demo/switch", dependencies=[Depends(require_demo)])
def switch_user(body: SwitchUser, request: Request, response: Response,
                user: User = Depends(require_demo_user), db: Session = Depends(get_db)) -> dict:
    """Become another of the fund's one-click users (a new session; the old one ends)."""
    target = db.execute(
        select(User).where(User.username == body.username.strip().lower(), User.demo_fund_id == user.demo_fund_id)
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No user {body.username} in this demo.")
    _sign_in(db, request, response, target, {"via": "demo role switcher", "from": user.username})
    return {"user": _me(db, target)}


@router.post("/api/demo/next-day", dependencies=[Depends(require_demo)])
def next_day(user: User = Depends(require_demo_user), db: Session = Depends(get_db)) -> dict:
    """Generate the demo fund's next business day and queue its run (analyst or approver)."""
    if user.role not in ("analyst", "approver"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot do this.")
    fund = db.get(Fund, user.demo_fund_id)
    as_of, job_id = generate_next_day(db, fund, user)
    db.commit()
    return {"fund": fund.code, "as_of": str(as_of), "job_id": job_id}
