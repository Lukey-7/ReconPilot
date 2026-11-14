"""A fund's business days: uploading and validating files, and the day's status.

Days are worked strictly in order (spec 7.5, the owner's decision): files for a
day can be uploaded only once the previous business day is signed off, and a
signed-off day's files never change. Each upload replaces earlier files of the
same kind for that day, then the whole set held for the day is validated again,
so files can arrive in several uploads.

Running a day queues a ``run_day`` job (see ``runner``) and answers 202 with the
job's id; ``GET /api/jobs/{id}`` reports its progress. Only the fund's latest
day can be run, and only until it is signed off.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import current_user, get_db, require_roles
from reconpilot_web.funds import fund_settings, get_fund, is_business_day, previous_business_day
from reconpilot_web.jobs import enqueue, job_payload
from reconpilot_web.models import AuditEntry, BusinessDay, Fund, InputFile, Job, User
from reconpilot_web.validation import (
    FILE_KINDS,
    KIND_BY_FILENAME,
    MAX_FILE_BYTES,
    MAX_ROWS,
    REQUIRED,
    ValidationReport,
    validate_files,
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

RUN_JOB_KIND = "run_day"

# Day statuses from which a run may be started (``uploaded`` means validation failed).
RUNNABLE_STATUSES = ("validated", "ready", "failed")

# Statuses whose NAV, checks and release status come from a finished run.
RUN_STATUSES = ("ready", "signed_off")

# How many error messages a VALIDATION_FAILED audit entry quotes (the counts are always complete).
AUDIT_ERROR_SAMPLE = 20

UPLOADS_OFF_MESSAGE = "Uploads are switched off in the demo."


def parse_as_of(value: str) -> date:
    """A day in the URL, ``YYYY-MM-DD`` only (422 otherwise)."""
    if _ISO_DATE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{value!r} is not a date in YYYY-MM-DD form.")


def get_day(db: Session, fund: Fund, as_of: date, *, for_update: bool = False) -> BusinessDay | None:
    query = select(BusinessDay).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of == as_of)
    if for_update:  # under the lock, read the row afresh rather than any copy already loaded
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.execute(query).scalar_one_or_none()


def day_files(db: Session, day: BusinessDay) -> dict[str, bytes]:
    """The day's stored files as ``{kind: bytes}``, exactly as uploaded."""
    rows = db.execute(
        select(InputFile.kind, InputFile.content).where(InputFile.business_day_id == day.id)
    ).all()
    return {kind: bytes(content) for kind, content in rows}


@dataclass(frozen=True)
class OrderProblem:
    """Why files for a day cannot be loaded yet, as ``day_order_problem`` finds it.

    ``code`` is one of ``BEFORE_START``, ``NOT_BUSINESS_DAY``, ``PREVIOUS_NOT_LOADED`` and
    ``PREVIOUS_NOT_SIGNED_OFF``; ``day`` is the date the reason is about (the start date,
    the day itself or the previous business day) and ``day_status`` that day's status.
    """

    code: str
    message: str
    day: date | None = None
    day_status: str | None = None


def day_order_problem(db: Session, fund: Fund, as_of: date) -> OrderProblem | None:
    """``None`` when files for ``as_of`` may be loaded: a business day of the fund, from its
    start date on, whose previous business day (if any) is signed off. Otherwise the reason.
    """
    if as_of < fund.start_date:
        return OrderProblem("BEFORE_START", f"{as_of} is before {fund.code}'s start date, {fund.start_date}.",
                            fund.start_date)
    if not is_business_day(fund, as_of):
        return OrderProblem("NOT_BUSINESS_DAY", f"{as_of} is not a business day for {fund.code}.", as_of)
    prev = previous_business_day(fund, as_of)
    if prev is not None:
        prev_day = get_day(db, fund, prev)
        if prev_day is None:
            return OrderProblem("PREVIOUS_NOT_LOADED", f"Sign off {prev} first.", prev)
        if prev_day.status != "signed_off":
            return OrderProblem("PREVIOUS_NOT_SIGNED_OFF", f"Sign off {prev} first.", prev, prev_day.status)
    return None


def check_day_order(db: Session, fund: Fund, as_of: date) -> None:
    """409 unless files for ``as_of`` may be loaded (see ``day_order_problem``)."""
    problem = day_order_problem(db, fund, as_of)
    if problem is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, problem.message)


def base_name(filename: str | None) -> str:
    """An uploaded file's name without any folder path a browser sent with it."""
    return (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()


def filename_kind(filename: str | None) -> str | None:
    """The file kind for an uploaded file's name (case-insensitive; any folder path ignored)."""
    return KIND_BY_FILENAME.get(base_name(filename).lower())


def _username(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user.username if user else None


def latest_run_job(db: Session, day: BusinessDay) -> Job | None:
    """The most recent ``run_day`` job for the day, if it has ever been run."""
    return db.execute(
        select(Job)
        .where(Job.kind == RUN_JOB_KIND, Job.payload["business_day_id"].as_integer() == day.id)
        .order_by(Job.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def live_release(db: Session, fund: Fund, day: BusinessDay) -> tuple[dict[str, Any], list[dict]]:
    """The day's one release status and its checks as clients see them (see ``release``).

    Both come from the day's current cases, so the day's record never contradicts
    the release endpoint: the engine's ``NAV release`` check is shown renamed and
    recomputed, exactly as ``GET .../release`` shows it.
    """
    from reconpilot_web import release  # release builds on this module

    cases = release.day_cases(db, fund, day)
    status_ = release.compute_release(day, cases, day.checks or [])
    checks = release.client_checks(day.checks, cases, float(fund_settings(fund)["materiality_bp"]))
    return status_.to_dict(), checks


def day_payload(db: Session, fund: Fund, day: BusinessDay) -> dict[str, Any]:
    files = db.execute(
        select(InputFile).where(InputFile.business_day_id == day.id)
    ).scalars().all()
    order = list(FILE_KINDS)
    files = sorted(files, key=lambda f: order.index(f.kind) if f.kind in order else len(order))
    has_run = day.status in RUN_STATUSES
    job = latest_run_job(db, day)
    prev = previous_business_day(fund, day.as_of)
    release_status, checks = live_release(db, fund, day) if has_run else (None, None)
    return {
        "fund": fund.code,
        "as_of": str(day.as_of),
        "status": day.status,
        "previous_business_day": str(prev) if prev else None,
        "files": [
            {
                "kind": f.kind,
                "filename": f.filename,
                "sha256": f.sha256,
                "size_bytes": f.size_bytes,
                "uploaded_by": _username(db, f.uploaded_by),
                "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
            }
            for f in files
        ],
        "validation": day.validation,
        "error": day.error,
        "run_by": _username(db, day.run_by),
        "run_at": day.run_at.isoformat() if day.run_at else None,
        "signed_off_by": _username(db, day.signed_off_by),
        "signed_off_at": day.signed_off_at.isoformat() if day.signed_off_at else None,
        "nav": {
            "nav": day.nav,
            "nav_per_share": day.nav_per_share,
            "prior_nav_per_share": day.prior_nav_per_share,
            "detail": day.nav_detail,
        } if has_run else None,
        "checks": checks,
        "release": release_status,
        "summary": day.summary if has_run else None,
        "job": job_payload(job) if job is not None else None,
    }


# --------------------------------------------------------------------------- routes

router = APIRouter(prefix="/api/funds/{code}/days", tags=["days"])


def _read_upload(upload: UploadFile, name: str) -> bytes:
    """The upload's bytes; 413 past the size limit, which is checked before reading it all."""
    content = upload.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"{name} is larger than {MAX_FILE_BYTES // 1024 // 1024} MB.")
    return content


@router.post("/{as_of}/files")
def upload_files(
    code: str,
    as_of: str,
    request: Request,
    files: list[UploadFile] = File(...),
    user: User = Depends(require_roles("analyst", "approver")),
    db: Session = Depends(get_db),
) -> dict:
    if request.app.state.settings.mode == "demo":
        raise HTTPException(status.HTTP_403_FORBIDDEN, UPLOADS_OFF_MESSAGE)
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    check_day_order(db, fund, day_date)

    # Map every file to its kind before storing anything.
    by_kind: dict[str, UploadFile] = {}
    unknown = []
    for upload in files:
        kind = filename_kind(upload.filename)
        if kind is None:
            unknown.append(upload.filename or "(no name)")
        elif kind in by_kind:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"{FILE_KINDS[kind]} was sent more than once.")
        else:
            by_kind[kind] = upload
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Not a file ReconPilot reads: {', '.join(unknown)}. Expected: {', '.join(FILE_KINDS.values())}.",
        )
    contents = {kind: _read_upload(upload, FILE_KINDS[kind]) for kind, upload in by_kind.items()}
    names = {kind: base_name(upload.filename)[:255] for kind, upload in by_kind.items()}

    # One row per day, created by the first upload; locked so uploads, runs and sign-off queue up.
    db.execute(
        insert(BusinessDay).values(fund_id=fund.id, as_of=day_date, status="uploaded")
        .on_conflict_do_nothing(constraint="business_days_fund_as_of")
    )
    day = get_day(db, fund, day_date, for_update=True)
    if day.status == "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{day_date} is signed off; its files cannot change.")
    if day.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{day_date} is being run; upload again when it finishes.")

    existing = {
        f.kind: f for f in db.execute(
            select(InputFile).where(InputFile.business_day_id == day.id)
        ).scalars()
    }
    uploaded = []
    for kind, content in contents.items():
        digest = hashlib.sha256(content).hexdigest()
        row = existing.get(kind)
        if row is None:
            row = InputFile(business_day_id=day.id, kind=kind)
            db.add(row)
        row.filename = names[kind]
        row.sha256 = digest
        row.size_bytes = len(content)
        row.content = content
        row.uploaded_by = user.id
        row.uploaded_at = func.now()
        uploaded.append({"filename": names[kind], "kind": kind, "sha256": digest, "size_bytes": len(content)})
    db.flush()

    report: ValidationReport = validate_files(day_files(db, day), day_date)
    day.status = "validated" if report.ok else "uploaded"
    day.validation = report.to_dict()
    day.error = None

    audit = DbAuditLog(db, fund_id=fund.id)
    audit.append(user.username, user.role, "FILES_UPLOADED", {"as_of": str(day_date), "files": uploaded})
    outcome = {"as_of": str(day_date), "errors": len(report.errors), "warnings": len(report.warnings)}
    if report.ok:
        audit.append(user.username, user.role, "VALIDATION_PASSED", outcome)
    else:
        outcome["first_errors"] = [
            f"{i.file}{f' row {i.row}' if i.row else ''}: {i.message}" for i in report.errors[:AUDIT_ERROR_SAMPLE]
        ]
        audit.append(user.username, user.role, "VALIDATION_FAILED", outcome)
    db.commit()
    return {"status": day.status, **report.to_dict()}


def next_business_day(fund: Fund, d: date) -> date:
    """The first business day of the fund after ``d``."""
    nxt = d + timedelta(days=1)
    while not is_business_day(fund, nxt):
        nxt += timedelta(days=1)
    return nxt


def days_payload(db: Session, fund: Fund) -> dict[str, Any]:
    """The fund's loaded business days, newest first, and the day that can be loaded next.

    ``next_day`` is the start date when nothing is loaded, the business day after
    the latest day once that day is signed off, and ``None`` otherwise (days are
    worked in order, spec 7.5).
    """
    rows = db.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund.id).order_by(BusinessDay.as_of.desc())
    ).scalars().all()
    if not rows:
        next_day: date | None = fund.start_date
    elif rows[0].status == "signed_off":
        next_day = next_business_day(fund, rows[0].as_of)
    else:
        next_day = None
    days = []
    for day in rows:
        has_run = day.status in RUN_STATUSES
        days.append({
            "as_of": str(day.as_of),
            "status": day.status,
            "nav_per_share": day.nav_per_share if has_run else None,
            "open_cases": (day.summary or {}).get("open_cases") if has_run else None,
            "run_at": day.run_at.isoformat() if day.run_at else None,
            "signed_off_by": _username(db, day.signed_off_by),
            "signed_off_at": day.signed_off_at.isoformat() if day.signed_off_at else None,
        })
    return {
        "fund": fund.code,
        "start_date": str(fund.start_date),
        "latest_day": str(rows[0].as_of) if rows else None,
        "next_day": str(next_day) if next_day else None,
        "days": days,
    }


@router.get("")
def list_days(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The fund's business days with their status, newest first (see ``days_payload``)."""
    return days_payload(db, get_fund(db, code))


@router.get("/{as_of}")
def read_day(code: str, as_of: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    day = get_day(db, fund, day_date)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {day_date}.")
    return day_payload(db, fund, day)


@router.post("/{as_of}/run", status_code=status.HTTP_202_ACCEPTED)
def start_run(
    code: str,
    as_of: str,
    user: User = Depends(require_roles("analyst", "approver")),
    db: Session = Depends(get_db),
) -> dict:
    """Queue a run of the day's validated files (202 with the job id).

    409 when the day is signed off, already running, has validation errors, is not
    the fund's latest day, or its previous business day is not signed off.
    """
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    check_day_order(db, fund, day_date)
    day = get_day(db, fund, day_date, for_update=True)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {day_date}.")
    if day.status == "signed_off":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{day_date} is signed off; it cannot be run again.")
    if day.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{day_date} is already running.")
    if day.status not in RUNNABLE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{day_date}'s files have validation errors; fix them before running.")
    later = db.execute(
        select(BusinessDay.as_of)
        .where(BusinessDay.fund_id == fund.id, BusinessDay.as_of > day_date)
        .order_by(BusinessDay.as_of)
        .limit(1)
    ).scalar_one_or_none()
    if later is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Only the latest day can be run; files for {later} are already loaded.")

    previous_status = day.status
    day.status = "running"
    day.error = None
    day.run_by = user.id
    job_id = enqueue(db, RUN_JOB_KIND, {"business_day_id": day.id, "user_id": user.id}, user.id)
    DbAuditLog(db, fund_id=fund.id).append(user.username, user.role, "RUN_STARTED", {
        "as_of": str(day_date),
        "job_id": job_id,
        "rerun": previous_status != "validated" or day.run_at is not None,
        "previous_status": previous_status,
    })
    db.commit()
    return {"job_id": job_id}


def intake_payload(db: Session, fund: Fund, as_of: date, *, demo: bool) -> dict[str, Any]:
    """Whether files for ``as_of`` can be loaded now and, if not, why (spec 7.5).

    ``open`` is true exactly when an analyst's or approver's upload would pass the
    day-order and lock checks; ``blocked`` is then ``None``. Otherwise ``blocked`` gives the
    first reason, in the order the upload route checks them, with the route's own message.
    """
    day = get_day(db, fund, as_of)
    prev = previous_business_day(fund, as_of)
    prev_day = get_day(db, fund, prev) if prev is not None else None
    blocked: dict[str, Any] | None = None
    if demo:
        blocked = {"code": "UPLOADS_OFF", "message": UPLOADS_OFF_MESSAGE, "day": None, "day_status": None}
    else:
        problem = day_order_problem(db, fund, as_of)
        if problem is not None:
            blocked = {"code": problem.code, "message": problem.message,
                       "day": str(problem.day) if problem.day else None, "day_status": problem.day_status}
        elif day is not None and day.status == "signed_off":
            blocked = {"code": "SIGNED_OFF", "message": f"{as_of} is signed off; its files cannot change.",
                       "day": str(as_of), "day_status": day.status}
        elif day is not None and day.status == "running":
            blocked = {"code": "RUNNING", "message": f"{as_of} is being run; upload again when it finishes.",
                       "day": str(as_of), "day_status": day.status}
    return {
        "fund": fund.code,
        "as_of": str(as_of),
        "open": blocked is None,
        "blocked": blocked,
        "day_status": day.status if day is not None else None,
        "previous_business_day": str(prev) if prev else None,
        "previous_status": prev_day.status if prev_day is not None else None,
        "following_day": str(next_business_day(fund, max(as_of, fund.start_date - timedelta(days=1)))),
        "expected_files": [
            {"kind": kind, "filename": name, "required": kind in REQUIRED} for kind, name in FILE_KINDS.items()
        ],
        "max_file_bytes": MAX_FILE_BYTES,
        "max_rows": MAX_ROWS,
    }


@router.get("/{as_of}/intake")
def read_intake(
    code: str, as_of: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """Whether the day can take files now, why not if it cannot, and the files it expects."""
    fund = get_fund(db, code)
    return intake_payload(db, fund, parse_as_of(as_of), demo=request.app.state.settings.mode == "demo")


def _seconds(start, end) -> float | None:
    return round((end - start).total_seconds(), 3) if start is not None and end is not None else None


def runs_payload(db: Session, fund: Fund, day: BusinessDay) -> dict[str, Any]:
    """Every ``run_day`` job for the day, newest first, with who started it and what it found."""
    jobs = db.execute(
        select(Job)
        .where(Job.kind == RUN_JOB_KIND, Job.payload["business_day_id"].as_integer() == day.id)
        .order_by(Job.id.desc())
    ).scalars().all()
    # Whether a run was a re-run is recorded when it is started, in its RUN_STARTED entry.
    started: dict[int, dict] = {}
    for payload in db.execute(
        select(AuditEntry.payload).where(AuditEntry.fund_id == fund.id, AuditEntry.action == "RUN_STARTED")
    ).scalars():
        if isinstance(payload, dict) and isinstance(payload.get("job_id"), int):
            started[payload["job_id"]] = payload
    runs = []
    for job in jobs:
        result = job.result or {}
        outcome = None
        if job.status == "done" and "skipped" not in result:
            rerun = result.get("rerun") or {}
            outcome = {
                "open_cases": result.get("open_cases"),
                "new_cases": result.get("new_cases"),
                "carried_cases": result.get("carried_cases"),
                "cleared_today": len(result.get("cleared_today") or []),
                "breaks": result.get("breaks"),
                "matches": result.get("matches"),
                "decisions_reapplied": len(rerun.get("decisions_reapplied") or []),
                "decisions_voided": len(rerun.get("decisions_voided") or []),
                "cases_withdrawn": len(rerun.get("cases_withdrawn") or []),
            }
        runs.append({
            "job_id": job.id,
            "status": job.status,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "started_by": _username(db, job.created_by),
            "rerun": bool(started.get(job.id, {}).get("rerun", False)),
            "queued_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "duration_seconds": _seconds(job.started_at, job.finished_at),
            "error": job.error,
            "outcome": outcome,
            "skipped": result.get("skipped"),
        })
    return {"fund": fund.code, "as_of": str(day.as_of), "runs": runs}


@router.get("/{as_of}/runs")
def list_runs(code: str, as_of: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The day's runs, newest first (404 when the day has no files)."""
    fund = get_fund(db, code)
    day_date = parse_as_of(as_of)
    day = get_day(db, fund, day_date)
    if day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No files have been uploaded for {day_date}.")
    return runs_payload(db, fund, day)


jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@jobs_router.get("/{job_id}")
def read_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No job {job_id}.")
    return job_payload(job)
