"""Running a business day through the engine and keeping the results (spec 7.3 to 7.5).

``run_day_job`` is the worker's handler for ``run_day`` jobs. It does in one
transaction (the worker's) what ``reconpilot run`` does with a run folder:

1. writes the day's stored files to a temporary folder and ``read_day``s them,
   exactly as the command line reads a data folder;
2. attaches the previous business day's open cash items (book items with their
   trades) and its open cases, from ``open_items`` and ``case_snapshots``;
3. calls ``pipeline.run_day`` with the fund's lifecycle and check settings, the
   database audit log and, only when the fund has AI switched on, the AI client
   with the database response cache;
4. stores the cases (bumping each one's ``version``), the day's snapshots,
   breaks and open items, and the NAV, checks and run summary on the day, and
   marks the day ``ready``.

Anything that raises rolls all of it back. The job is retried, and after its
last attempt ``run_day_failed`` marks the day ``failed`` with the error.

Re-running (spec 7.5) is allowed only for the fund's latest day before it is
signed off. Decisions taken on that day are re-applied, through the engine's
``ReviewSession`` and as the person who took them, to cases that still exist
for the same security with the same suggested cause; any other decision is
voided (``DECISION_VOIDED_BY_RERUN``), and a case from the earlier run that the
new run no longer raises is withdrawn (``CASE_WITHDRAWN_BY_RERUN``).

The AI provider comes from the environment, never the database: the first of
``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY`` and ``GOOGLE_API_KEY`` that is set, or
``RP_AI_PROVIDER``; ``RP_AI_MODEL``, ``RP_AI_EFFORT`` and ``RP_AI_TIMEOUT`` override
the engine's defaults. A demo visitor's fund never calls a provider, key or not: its
AI answers come from the demo's pre-filled cache (``demo_ai_client``), and anything
not cached falls back to the rules.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from reconpilot.ai import make_client
from reconpilot.matching import carry_forward
from reconpilot.models import CarriedItem, Case, CashLine, DayData
from reconpilot.pipeline import DayResult, run_day
from reconpilot.review import PermissionDenied, ReviewError, ReviewSession
from reconpilot.storage import case_from_dict, case_to_dict, read_day, trade_from_dict, trade_to_dict
from reconpilot_web import jobs
from reconpilot_web.aicache import DbResponseCache, demo_client
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import SYSTEM_ACTOR, SYSTEM_ROLE
from reconpilot_web.funds import fund_check_settings, fund_lifecycle, fund_settings, previous_business_day
from reconpilot_web.models import (
    BreakRow,
    BusinessDay,
    CaseRow,
    CaseSnapshot,
    Decision,
    Fund,
    InputFile,
    Job,
    OpenItem,
    User,
)
from reconpilot_web.validation import FILE_KINDS, engine_bytes

JOB_KIND = "run_day"


class RunError(Exception):
    """A day that cannot be run as asked (the job fails with this message)."""


# --------------------------------------------------------------------------- inputs


def ai_client():
    """The AI client from the environment, or ``None`` when no provider key is set."""
    timeout = os.environ.get("RP_AI_TIMEOUT", "").strip()
    return make_client(
        os.environ.get("RP_AI_PROVIDER", "").strip() or None,
        os.environ.get("RP_AI_MODEL", "").strip() or None,
        os.environ.get("RP_AI_EFFORT", "").strip() or "medium",
        float(timeout) if timeout else 120.0,
    )


def demo_ai_client():
    """The demo's AI: answers from the pre-filled cache only (``aicache.CacheOnlyClient``)."""
    return demo_client()


def load_day_data(session: Session, day: BusinessDay) -> DayData:
    """The day's stored files read by the engine's own ``storage.read_day``."""
    rows = session.execute(
        select(InputFile.kind, InputFile.content).where(InputFile.business_day_id == day.id)
    ).all()
    with tempfile.TemporaryDirectory(prefix="reconpilot_day_") as tmp:
        folder = Path(tmp)
        for kind, content in rows:
            if kind in FILE_KINDS:
                (folder / FILE_KINDS[kind]).write_bytes(engine_bytes(bytes(content)))
        return read_day(folder)


def book_item_to_dict(item: CarriedItem) -> dict:
    return {
        "reference": item.reference,
        "security_id": item.security_id,
        "amount": item.amount,
        "origin_date": str(item.origin_date),
        "trade": trade_to_dict(item.trade) if item.trade is not None else None,
    }


def book_item_from_dict(d: dict) -> CarriedItem:
    return CarriedItem(d["reference"], d["security_id"], d["amount"], date.fromisoformat(d["origin_date"]),
                       trade_from_dict(d["trade"]) if d.get("trade") else None)


def cash_line_to_dict(line: CashLine) -> dict:
    return {**asdict(line), "value_date": str(line.value_date)}


def cash_line_from_dict(d: dict) -> CashLine:
    return CashLine(d["entry_id"], date.fromisoformat(d["value_date"]), d["security_id"], d["reference"],
                    d["description"], d["amount"])


def carried_items(session: Session, day: BusinessDay) -> tuple[list[CarriedItem], list[CashLine]]:
    """A day's open items, in the order the engine produced them."""
    rows = session.execute(
        select(OpenItem).where(OpenItem.business_day_id == day.id).order_by(OpenItem.id)
    ).scalars().all()
    rows = sorted(rows, key=lambda r: (r.data.get("position", 0), r.id))
    book = [book_item_from_dict(r.data) for r in rows if r.side == "book"]
    cust = [cash_line_from_dict(r.data) for r in rows if r.side == "custodian"]
    return book, cust


def open_cases_at(session: Session, fund: Fund, as_of: date) -> list[Case]:
    """The cases open at the end of ``as_of`` (its ledger snapshot), largest NAV impact first."""
    rows = session.execute(
        select(CaseSnapshot.data)
        .where(CaseSnapshot.fund_id == fund.id, CaseSnapshot.as_of == as_of, CaseSnapshot.is_open.is_(True))
    ).scalars().all()
    cases = [case_from_dict(data) for data in rows]
    return sorted(cases, key=lambda c: (-abs(c.nav_impact), c.case_id))  # impact.sort_by_impact


def _get_day(session: Session, fund: Fund, as_of: date) -> BusinessDay | None:
    return session.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of == as_of)
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- outputs


def _iso(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _cat(value) -> str | None:
    return value.value if value is not None else None


def _case_columns(case: Case) -> dict[str, Any]:
    return {
        "security_id": case.security_id,
        "category": case.category.value,
        "status": case.status,
        "final_category": _cat(case.final_category),
        "ai_category": _cat(case.ai_category),
        "ai_flag": case.ai_flag,
        "nav_impact": case.nav_impact,
        "nav_impact_bp": case.nav_impact_bp,
        "gross_exposure": case.gross_exposure,
        "material": case.material,
        "escalated": case.escalated,
        "sla_breached": case.sla_breached,
        "age_days": case.age_days,
        "age_bucket": case.age_bucket,
        "first_seen": _iso(case.first_seen),
        "cleared_on": _iso(case.cleared_on),
        "resolved_category": _cat(case.resolved_category),
        "data": case_to_dict(case),
    }


def upsert_case(session: Session, fund: Fund, case: Case, as_of: date) -> CaseRow:
    """Write a case's current state, bumping its ``version``."""
    row = session.get(CaseRow, (fund.id, case.case_id), with_for_update=True)
    if row is None:
        row = CaseRow(fund_id=fund.id, case_id=case.case_id, version=1)
        session.add(row)
    else:
        row.version = row.version + 1
    for key, value in _case_columns(case).items():
        setattr(row, key, value)
    row.last_as_of = as_of
    return row


def _snapshot(fund: Fund, day: BusinessDay, case: Case, is_open: bool) -> CaseSnapshot:
    return CaseSnapshot(
        fund_id=fund.id, case_id=case.case_id, as_of=day.as_of, business_day_id=day.id,
        status=case.status, category=case.category.value, is_open=is_open,
        nav_impact=case.nav_impact, material=case.material, escalated=case.escalated,
        sla_breached=case.sla_breached, age_days=case.age_days, data=case_to_dict(case),
    )


def _persist(session: Session, fund: Fund, day: BusinessDay, data: DayData, result: DayResult) -> None:
    """Replace the day's cases, snapshots, breaks and open items with ``result``."""
    for case in result.cleared + result.open_cases:
        upsert_case(session, fund, case, day.as_of)

    session.execute(delete(CaseSnapshot).where(CaseSnapshot.fund_id == fund.id, CaseSnapshot.as_of == day.as_of))
    session.add_all([_snapshot(fund, day, c, False) for c in result.cleared])
    session.add_all([_snapshot(fund, day, c, True) for c in result.open_cases])

    case_of_break = {b: c.case_id for c in result.open_cases for b in c.break_ids}
    session.execute(delete(BreakRow).where(BreakRow.business_day_id == day.id))
    session.add_all([
        BreakRow(business_day_id=day.id, break_id=b.break_id, case_id=case_of_break.get(b.break_id),
                 kind=b.kind.value, security_id=b.security_id or "", book_value=b.book_value,
                 custodian_value=b.custodian_value, difference=b.difference, reference=b.reference or "",
                 note=b.note or "")
        for b in result.recon.breaks
    ])

    book, cust = carry_forward(result.recon, data)
    session.execute(delete(OpenItem).where(OpenItem.business_day_id == day.id))
    position = 0
    for item in book:
        session.add(OpenItem(business_day_id=day.id, side="book", reference=item.reference,
                             security_id=item.security_id, amount=item.amount, origin_date=item.origin_date,
                             data={**book_item_to_dict(item), "position": position}))
        position += 1
    for line in cust:
        session.add(OpenItem(business_day_id=day.id, side="custodian", reference=line.reference,
                             security_id=line.security_id, amount=line.amount, origin_date=line.value_date,
                             data={**cash_line_to_dict(line), "position": position}))
        position += 1
    session.flush()


# --------------------------------------------------------------------------- re-runs


def _earlier_run(session: Session, fund: Fund, day: BusinessDay) -> dict[str, dict]:
    """Cases the day's previous run raised or cleared: ``{case_id: snapshot data}``."""
    rows = session.execute(
        select(CaseSnapshot.case_id, CaseSnapshot.data)
        .where(CaseSnapshot.fund_id == fund.id, CaseSnapshot.as_of == day.as_of)
    ).all()
    return {case_id: data for case_id, data in rows}


def _reconcile_rerun(
    session: Session,
    fund: Fund,
    day: BusinessDay,
    earlier: dict[str, dict],
    prior_ids: set[str],
    result: DayResult,
    audit: DbAuditLog,
    actor: str,
    role: str,
) -> dict[str, list]:
    """Re-apply the day's decisions that still fit, void the rest and withdraw vanished cases."""
    now_cases = {c.case_id: c for c in result.cleared + result.open_cases}
    open_now = {c.case_id: c for c in result.open_cases}
    withdrawn: list[str] = []
    for case_id in sorted(earlier):
        before = earlier[case_id]
        now = now_cases.get(case_id)
        if now is not None and now.security_id == before.get("security_id"):
            continue
        withdrawn.append(case_id)
        audit.append(actor, role, "CASE_WITHDRAWN_BY_RERUN", {
            "case_id": case_id, "as_of": str(day.as_of), "security_id": before.get("security_id"),
            "category": before.get("category"),
            "reason": "the re-run no longer raises this case" if now is None
            else f"the re-run raises {case_id} for {now.security_id} instead",
        })
        if now is None and case_id not in prior_ids:
            row = session.get(CaseRow, (fund.id, case_id), with_for_update=True)
            if row is not None:
                session.delete(row)

    decisions = session.execute(
        select(Decision)
        .where(Decision.business_day_id == day.id, Decision.voided_at.is_(None))
        .order_by(Decision.created_at, Decision.id)
    ).scalars().all()
    reapplied: list[int] = []
    voided: list[int] = []
    for d in decisions:
        case = open_now.get(d.case_id)
        before = earlier.get(d.case_id, {})
        reason = None
        if case is None:
            reason = "the case is no longer open after the re-run"
        elif case.security_id != before.get("security_id"):
            reason = "the case now concerns a different security"
        elif case.category.value != d.category:
            reason = f"the suggested cause changed from {d.category} to {case.category.value}"
        if reason is None:
            user = session.get(User, d.user_id)
            review = ReviewSession(result.open_cases, audit, user.username if user else str(d.user_id), d.role)
            try:
                if d.decision == "approve":
                    review.approve(d.case_id, d.note)
                elif d.decision == "reject":
                    review.reject(d.case_id, d.note)
                else:
                    review.reclassify(d.case_id, d.final_category, d.note)
            except (PermissionDenied, ReviewError, ValueError) as exc:
                reason = f"it could not be applied again: {exc}"
        if reason is None:
            reapplied.append(d.id)
            continue
        d.voided_at = func.now()
        d.void_reason = reason
        voided.append(d.id)
        audit.append(actor, role, "DECISION_VOIDED_BY_RERUN", {
            "case_id": d.case_id, "as_of": str(day.as_of), "decision_id": d.id, "decision": d.decision,
            "decided_by": d.user_id, "decided_role": d.role, "reason": reason,
        })
    return {"decisions_reapplied": reapplied, "decisions_voided": voided, "cases_withdrawn": withdrawn}


# --------------------------------------------------------------------------- the job


def _actor(session: Session, user_id: int | None) -> tuple[str, str]:
    user = session.get(User, user_id) if user_id is not None else None
    return (user.username, user.role) if user is not None else (SYSTEM_ACTOR, SYSTEM_ROLE)


def run_day_job(session: Session, payload: dict) -> dict:
    """Run one business day and persist everything in ``session``'s transaction (see module doc)."""
    day = session.get(BusinessDay, int(payload["business_day_id"]))
    if day is None:
        raise RunError(f"no business day {payload['business_day_id']}")
    if day.status != "running":
        # A duplicate or stale job: the day was run, re-uploaded or signed off since.
        return {"skipped": f"{day.as_of} is {day.status}, not waiting to run"}
    fund = session.get(Fund, day.fund_id)
    actor, role = _actor(session, payload.get("user_id"))

    later = session.execute(
        select(BusinessDay.as_of).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of > day.as_of).limit(1)
    ).scalar_one_or_none()
    if later is not None:
        raise RunError(f"only the latest day can be run; {later} has already been loaded")

    prev = previous_business_day(fund, day.as_of)
    prior_open: list[Case] = []
    book_items: list[CarriedItem] = []
    cust_lines: list[CashLine] = []
    if prev is not None:
        prev_day = _get_day(session, fund, prev)
        if prev_day is None or prev_day.status != "signed_off":
            raise RunError(f"Sign off {prev} first.")
        book_items, cust_lines = carried_items(session, prev_day)
        prior_open = open_cases_at(session, fund, prev)

    data = load_day_data(session, day)
    if data.as_of != day.as_of:
        raise RunError(f"fund.csv is for {data.as_of}, not {day.as_of}")
    data.carried_book_items, data.carried_custodian_lines = book_items, cust_lines
    earlier = _earlier_run(session, fund, day)

    settings = fund_settings(fund)
    use_ai = bool(settings["ai_enabled"])
    client = (demo_ai_client() if fund.is_demo else ai_client()) if use_ai else None
    audit = DbAuditLog(session, fund_id=fund.id)
    cache_session = Session(bind=session.get_bind()) if client is not None else None
    try:
        result = run_day(
            data, prior_open, fund_lifecycle(fund), use_ai=use_ai, ai_client=client,
            ai_cache=DbResponseCache(cache_session, autocommit=True) if cache_session is not None else None,
            audit=audit, actor=actor, role=role, check_settings=fund_check_settings(fund) or None,
        )
    finally:
        if cache_session is not None:
            cache_session.close()

    # Hold the day from here to commit, and make sure nothing changed it while the engine ran.
    session.refresh(day, with_for_update=True)
    if day.status != "running":
        raise RunError(f"{day.as_of} became {day.status} while it was being run")

    recon, nav, cases = result.recon, result.nav, result.open_cases
    # The same entry the command line writes after a run, so the two audit trails match.
    audit.append(actor, role, "CASES_RAISED", {
        "matches": len(recon.matches), "breaks": len(recon.breaks), "open_cases": len(cases),
        "cleared_today": [c.case_id for c in result.cleared],
        "nav_per_share": nav.nav_per_share,
        "material_cases": [c.case_id for c in cases if c.material],
        "checks": {c.name: c.status for c in result.checks},
    })

    rerun = _reconcile_rerun(session, fund, day, earlier, {c.case_id for c in prior_open}, result,
                             audit, actor, role) if earlier else None
    _persist(session, fund, day, data, result)

    summary = {
        "as_of": str(day.as_of),
        "previous_day": str(prev) if prev else None,
        "matches": len(recon.matches),
        "breaks": len(recon.breaks),
        "open_cases": len(cases),
        "new_cases": sum(1 for c in cases if c.first_seen == str(day.as_of)),
        "carried_cases": len(prior_open),
        "carried_cash_items": len(book_items) + len(cust_lines),
        "cleared_today": [c.case_id for c in result.cleared],
        "pending": sum(1 for c in cases if c.status == "PENDING"),
        "material": sum(1 for c in cases if c.material),
        "escalated": sum(1 for c in cases if c.escalated),
        "sla_breached": sum(1 for c in cases if c.sla_breached),
        "ai": {
            "enabled": use_ai,
            "available": client is not None,
            "provider": client.provider if client is not None else None,
            "model": client.model if client is not None else None,
            "disagreements": sum(1 for c in cases if c.ai_flag),
        },
        "rerun": rerun,
    }
    day.nav = nav.nav
    day.nav_per_share = nav.nav_per_share
    day.prior_nav_per_share = nav.prior_nav_per_share
    day.nav_detail = {**asdict(nav), "movement": nav.movement}
    day.checks = [asdict(c) for c in result.checks]
    day.release_ready = None  # computed from the current cases by the release module
    day.release = None
    day.summary = summary
    day.status = "ready"
    day.error = None
    day.run_at = func.now()
    audit.append(actor, role, "RUN_FINISHED", {
        "as_of": str(day.as_of), "open_cases": summary["open_cases"], "new_cases": summary["new_cases"],
        "cleared_today": summary["cleared_today"], "breaks": summary["breaks"],
        "nav_per_share": nav.nav_per_share, "ai": summary["ai"], "rerun": rerun,
    })
    session.flush()
    return summary


def run_day_failed(session: Session, job: Job, error: str, final: bool) -> None:
    """After a failed attempt: audit it, and once the job gives up mark the day ``failed``."""
    day = session.get(BusinessDay, int((job.payload or {}).get("business_day_id", 0)), with_for_update=True)
    if day is None or day.status != "running":
        return
    DbAuditLog(session, fund_id=day.fund_id).append(SYSTEM_ACTOR, SYSTEM_ROLE, "RUN_FAILED", {
        "as_of": str(day.as_of), "job_id": job.id, "attempt": job.attempts, "max_attempts": job.max_attempts,
        "error": error, "will_retry": not final,
    })
    if final:
        day.status = "failed"
        day.error = error


jobs.register(JOB_KIND, run_day_job, on_failure=run_day_failed)
