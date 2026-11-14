"""The audit log viewer (spec section 8): read, filter, verify and export the hash chain.

Routes under ``/api/audit``, for any signed-in role (reading the log is how a control
team checks the desk, so viewers may too). The chain is global, so entries without a
fund (sign-ins, user creation, chain verifications) are part of the log as well.

Filters, shared by the list and the CSV export, every one optional:

``fund``
    A fund code; absent means every entry, funds and system alike.
``as_of``
    One business day's trail, exactly the entries ``GET .../days/{as_of}/audit`` shows
    (``daytrail.day_window``); needs ``fund``.
``from``, ``to``
    When the entry was recorded, inclusive: an ISO date (a whole UTC day) or an ISO
    date-time with an offset, so a browser can send the user's local day as instants.
``actor``, ``case``
    A username or a case id, case-insensitive.
``action``
    One or more action codes, comma-separated.

The list is newest first and paged by keyset on ``seq``, so a page never shifts when new
entries arrive. One entry can be read with its own integrity (its hash recomputes, and it
links to the entry before it). ``POST /verify`` re-checks the whole chain on the server
and records that it did, with what it found, as ``AUDIT_CHAIN_VERIFIED``. The CSV export
holds every matching entry in chain order with its stored payload and hashes, so each
row's hash recomputes with the engine's ``record_hash`` and an unfiltered export
re-verifies end to end; each download is audited as ``EXPORT_DOWNLOADED``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import ColumnElement, Select, false, func, select, text
from sqlalchemy.orm import Session

from reconpilot.audit import GENESIS, record_hash
from reconpilot_web.auditlog import AUDIT_LOCK_KEY, DbAuditLog, verify_chain
from reconpilot_web.auth import current_user, get_db
from reconpilot_web.days import parse_as_of
from reconpilot_web.daytrail import day_window
from reconpilot_web.funds import get_fund
from reconpilot_web.models import AuditEntry, Fund, User
from reconpilot_web.mi import CSV_MEDIA_TYPE, EXPORT_ACTION

VERIFY_ACTION = "AUDIT_CHAIN_VERIFIED"
AUDIT_CSV_EXPORT = "audit_csv"

DEFAULT_PAGE = 50
MAX_PAGE = 200

# The most entries one CSV export may hold; past it the filters must be narrowed.
MAX_EXPORT_ROWS = 100_000

CSV_COLUMNS = ("seq", "ts", "actor", "role", "action", "fund", "case_id", "payload", "prev_hash", "hash")

ACTION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


# --------------------------------------------------------------------------- filters


@dataclass
class AuditFilters:
    """The filters as asked, normalised; ``echo`` is what was asked, for the export's audit entry."""

    fund: Fund | None = None
    as_of: date | None = None
    since: str | None = None  # a stored ``ts`` (UTC, seconds) the entry is at or after
    until: str | None = None  # a stored ``ts`` the entry is at or before
    actor: str | None = None
    actions: list[str] | None = None
    case_id: str | None = None
    echo: dict[str, Any] | None = None


def _stored_ts(moment: datetime) -> str:
    """``moment`` written as ``audit_log.ts`` is (UTC, seconds, ``+00:00``), so strings compare as times."""
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _bound(value: str, *, end: bool) -> str:
    """An inclusive bound on ``ts`` from an ISO date (a whole UTC day) or a date-time with an offset."""
    text = value.strip()
    try:
        if len(text) == 10:
            day = date.fromisoformat(text)
            start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            return _stored_ts(start + timedelta(days=1) - timedelta(seconds=1) if end else start)
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"'{value}' is not a date (YYYY-MM-DD) or a date and time.") from None
    if moment.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"'{value}' needs a time zone offset (for example Z or +01:00).")
    return _stored_ts(moment)


def _actions(value: str | None) -> list[str] | None:
    if value is None or not value.strip():
        return None
    actions = sorted({a.strip().upper() for a in value.split(",") if a.strip()})
    bad = [a for a in actions if not ACTION_PATTERN.match(a)]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Not an audit action: {', '.join(bad)}.")
    return actions or None


def audit_filters(
    fund: str | None = Query(None, max_length=32),
    as_of: str | None = Query(None, max_length=10),
    from_: str | None = Query(None, alias="from", max_length=40),
    to: str | None = Query(None, max_length=40),
    actor: str | None = Query(None, max_length=128),
    action: str | None = Query(None, max_length=1000),
    case: str | None = Query(None, max_length=64),
    db: Session = Depends(get_db),
) -> AuditFilters:
    """The filters from the query string (a dependency), 404 for an unknown fund and 422 for a bad value."""
    filters = AuditFilters()
    echo: dict[str, Any] = {}
    if fund and fund.strip():
        filters.fund = get_fund(db, fund.strip())
        echo["fund"] = filters.fund.code
    if as_of and as_of.strip():
        if filters.fund is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A business day filter needs a fund.")
        filters.as_of = parse_as_of(as_of.strip())
        echo["as_of"] = str(filters.as_of)
    if from_ and from_.strip():
        filters.since = _bound(from_, end=False)
        echo["from"] = from_.strip()
    if to and to.strip():
        filters.until = _bound(to, end=True)
        echo["to"] = to.strip()
    if filters.since and filters.until and filters.since > filters.until:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The 'from' date is after the 'to' date.")
    if actor and actor.strip():
        filters.actor = actor.strip().lower()
        echo["actor"] = filters.actor
    filters.actions = _actions(action)
    if filters.actions:
        echo["action"] = ",".join(filters.actions)
    if case and case.strip():
        filters.case_id = case.strip().upper()
        echo["case"] = filters.case_id
    filters.echo = echo
    return filters


def conditions(db: Session, filters: AuditFilters) -> list[ColumnElement[bool]]:
    """SQL conditions for ``filters``."""
    where: list[ColumnElement[bool]] = []
    if filters.fund is not None:
        where.append(AuditEntry.fund_id == filters.fund.id)
    if filters.as_of is not None and filters.fund is not None:
        window = day_window(db, filters.fund, filters.as_of)
        where.extend(window if window is not None else [false()])
    if filters.since is not None:
        where.append(AuditEntry.ts >= filters.since)
    if filters.until is not None:
        where.append(AuditEntry.ts <= filters.until)
    if filters.actor is not None:
        where.append(func.lower(AuditEntry.actor) == filters.actor)
    if filters.actions:
        where.append(AuditEntry.action.in_(filters.actions))
    if filters.case_id is not None:
        where.append(func.upper(AuditEntry.case_id) == filters.case_id)
    return where


# --------------------------------------------------------------------------- entries


def _fund_codes(db: Session, entries: list[AuditEntry]) -> dict[int, str]:
    ids = {e.fund_id for e in entries if e.fund_id is not None}
    if not ids:
        return {}
    return dict(db.execute(select(Fund.id, Fund.code).where(Fund.id.in_(ids))).all())


def entry_payload(entry: AuditEntry, codes: dict[int, str]) -> dict[str, Any]:
    return {
        "seq": entry.seq,
        "ts": entry.ts,
        "actor": entry.actor,
        "role": entry.role,
        "action": entry.action,
        "fund": codes.get(entry.fund_id) if entry.fund_id is not None else None,
        "case_id": entry.case_id,
        "payload": entry.payload,
        "prev_hash": entry.prev_hash,
        "hash": entry.hash,
    }


def _record(entry: AuditEntry) -> dict[str, Any]:
    """The engine's record fields of an entry, without its hash."""
    return {
        "seq": entry.seq, "ts": entry.ts, "actor": entry.actor, "role": entry.role, "action": entry.action,
        "payload": entry.payload, "prev_hash": entry.prev_hash,
    }


def _count(db: Session, where: list[ColumnElement[bool]]) -> int:
    return db.execute(select(func.count()).select_from(AuditEntry).where(*where)).scalar_one()


def _matching(where: list[ColumnElement[bool]]) -> Select:
    return select(AuditEntry).where(*where)


def page_payload(db: Session, filters: AuditFilters, limit: int, before: int | None) -> dict[str, Any]:
    where = conditions(db, filters)
    page_where = [*where, AuditEntry.seq < before] if before is not None else where
    rows = list(db.execute(
        _matching(page_where).order_by(AuditEntry.seq.desc()).limit(limit + 1)
    ).scalars())
    entries, more = rows[:limit], len(rows) > limit

    newer = _count(db, [*where, AuditEntry.seq >= before]) if before is not None else 0
    newer_before: int | None = None
    if newer > limit:
        # The page above this one holds the ``limit`` matching entries just above it: those
        # below the (limit + 1)th matching entry counted upwards from ``before``.
        newer_before = db.execute(
            select(AuditEntry.seq).where(*where, AuditEntry.seq >= before)
            .order_by(AuditEntry.seq).offset(limit).limit(1)
        ).scalar_one()
    codes = _fund_codes(db, entries)
    return {
        "entries": [entry_payload(e, codes) for e in entries],
        "total": _count(db, where),
        "newer": newer,
        "has_newer": newer > 0,
        "newer_before": newer_before,
        "next_before": entries[-1].seq if more and entries else None,
        "latest_seq": db.execute(select(func.max(AuditEntry.seq))).scalar_one_or_none() or 0,
    }


def csv_bytes(db: Session, filters: AuditFilters) -> tuple[bytes, int]:
    """Every matching entry in chain order as CSV (see module doc), and how many rows it holds."""
    where = conditions(db, filters)
    rows = _count(db, where)
    if rows > MAX_EXPORT_ROWS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{rows:,} entries match; an export holds at most {MAX_EXPORT_ROWS:,}. Narrow the filters.",
        )
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    codes = dict(db.execute(select(Fund.id, Fund.code)).all())
    for entry in db.execute(
        _matching(where).order_by(AuditEntry.seq).execution_options(yield_per=1000)
    ).scalars():
        writer.writerow([
            entry.seq, entry.ts, entry.actor, entry.role, entry.action,
            codes.get(entry.fund_id, "") if entry.fund_id is not None else "",
            entry.case_id or "",
            json.dumps(entry.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            entry.prev_hash, entry.hash,
        ])
    return out.getvalue().encode("utf-8"), rows


# --------------------------------------------------------------------------- routes

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_entries(
    filters: AuditFilters = Depends(audit_filters),
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    before: int | None = Query(None, ge=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """One page of matching entries, newest first (see module doc). Any signed-in role."""
    return page_payload(db, filters, limit, before)


@router.get("/facets")
def facets(
    fund: str | None = Query(None, max_length=32),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """The actors and actions present in the log (or the fund's part of it), for the filter menus."""
    where: list[ColumnElement[bool]] = []
    if fund and fund.strip():
        where.append(AuditEntry.fund_id == get_fund(db, fund.strip()).id)
    actors = db.execute(select(AuditEntry.actor).where(*where).distinct().order_by(AuditEntry.actor)).scalars()
    actions = db.execute(select(AuditEntry.action).where(*where).distinct().order_by(AuditEntry.action)).scalars()
    return {"actors": list(actors), "actions": list(actions)}


@router.get("/entries/{seq}")
def read_entry(seq: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """One entry in full, with whether its hash recomputes and it links to the entry before it."""
    entry = db.execute(select(AuditEntry).where(AuditEntry.seq == seq)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"There is no audit entry #{seq}.")
    if seq == 1:
        expected_prev: str | None = GENESIS
    else:
        expected_prev = db.execute(select(AuditEntry.hash).where(AuditEntry.seq == seq - 1)).scalar_one_or_none()
    return {
        **entry_payload(entry, _fund_codes(db, [entry])),
        "hash_ok": record_hash(_record(entry)) == entry.hash,
        "linked": expected_prev is not None and entry.prev_hash == expected_prev,
    }


@router.post("/verify")
def verify(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Re-check every hash in the chain on the server, and record the check (see module doc).

    Appends wait while the chain is checked, so the entry recording the check comes
    straight after the last entry it covered.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": AUDIT_LOCK_KEY})
    chain_ok, broken_at = verify_chain(db)
    count, last_seq = db.execute(select(func.count(AuditEntry.id), func.max(AuditEntry.seq))).one()
    last_hash = db.execute(
        select(AuditEntry.hash).where(AuditEntry.seq == last_seq)
    ).scalar_one_or_none() if last_seq is not None else None
    record = DbAuditLog(db).append(user.username, user.role, VERIFY_ACTION, {
        "intact": chain_ok,
        "broken_at": broken_at,
        "entries": count,
        "last_seq": last_seq,
    })
    db.commit()
    return {
        "chain_ok": chain_ok,
        "broken_at": broken_at,
        "entries": count,
        "last_seq": last_seq,
        "last_hash": last_hash,
        "verified_at": record["ts"],
        "verified_by": user.username,
        "seq": record["seq"],
    }


@router.get("/export.csv")
def export_csv(
    filters: AuditFilters = Depends(audit_filters),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Every matching entry as CSV in chain order, audited. Any signed-in role."""
    content, rows = csv_bytes(db, filters)
    scope = filters.fund.code if filters.fund is not None else "ALL"
    filename = f"audit_{scope}_{datetime.now(timezone.utc).date()}.csv"
    DbAuditLog(db, fund_id=filters.fund.id if filters.fund is not None else None).append(
        user.username, user.role, EXPORT_ACTION, {
            "export": AUDIT_CSV_EXPORT,
            "filename": filename,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "rows": rows,
            "filters": filters.echo or {},
        })
    db.commit()
    return Response(content, media_type=CSV_MEDIA_TYPE, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })
