"""Cases across days: ageing, escalation, SLAs and automatic clearing.

Each run directory keeps one snapshot per business day under ``state/<date>/``:

* ``ledger.json``      every case seen so far, open and cleared
* ``open_items.json``  cash items still unmatched at the end of that day

The next day's run starts from the latest earlier snapshot. Its open cash
items are fed back into matching, so a late settlement that arrives today
matches yesterday's book item. Its open cases are rolled forward:

* a case whose security still has breaks today carries on, keeping its
  identifier, first-seen date and (if the cause is unchanged) its review
  decision;
* a case whose security has no breaks today is cleared automatically, with
  an audit entry. A booked trade that the custodian settles on a later day is
  recorded as resolved as a late settlement (TIMING), whatever it was first
  thought to be;
* age is counted in business days and bucketed 0-1, 2-5 and >5;
* material cases, and cases older than the escalation limit, are escalated
  with an audit entry and need an approver's decision before sign-off;
* a case open longer than its SLA is reported as a breach, with an audit entry.

Re-running a day replaces that day's snapshot, so runs are repeatable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from reconpilot.audit import AuditLog
from reconpilot.matching import ReconResult, carry_forward
from reconpilot.models import BreakKind, CarriedItem, Case, CashLine, Category
from reconpilot.storage import load_cases, save_cases

STATE_DIR = "state"
BUCKETS = ("0-1", "2-5", ">5")


@dataclass
class LifecycleSettings:
    materiality_bp: float = 1.0
    escalate_after_days: int = 5  # escalate when open longer than this
    sla_days_material: int = 2
    sla_days_other: int = 5


def business_days_between(start: date, end: date) -> int:
    """Weekdays after ``start`` up to and including ``end``."""
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def age_bucket(days: int) -> str:
    return "0-1" if days <= 1 else "2-5" if days <= 5 else ">5"


def current_category(case: Case) -> Category:
    """The cause a person would read off the case right now."""
    if case.resolved_category:
        return case.resolved_category
    if case.final_category:
        return case.final_category
    if case.ai_status == "ACCEPTED" and case.ai_category:
        return case.ai_category
    return case.category


def days_to_resolve(case: Case) -> int | None:
    if not case.cleared_on or not case.first_seen:
        return None
    return business_days_between(date.fromisoformat(case.first_seen), date.fromisoformat(case.cleared_on))


def _audit(audit: AuditLog | None, actor: str, role: str, action: str, payload: dict) -> None:
    if audit is not None:
        audit.append(actor, role, action, payload)


def roll_forward(
    prior_open: list[Case],
    today_cases: list[Case],
    recon: ReconResult,
    as_of: date,
    settings: LifecycleSettings | None = None,
    audit: AuditLog | None = None,
    actor: str = "system",
    role: str = "analyst",
) -> tuple[list[Case], list[Case]]:
    """Merge today's cases with yesterday's open ones. Returns (open, cleared today)."""
    settings = settings or LifecycleSettings()
    kinds = {b.break_id: b.kind.value for b in recon.breaks}
    today_by_sid = {c.security_id: c for c in today_cases}
    prior_by_sid = {c.security_id: c for c in prior_open}

    cleared: list[Case] = []
    for p in prior_open:
        if p.security_id in today_by_sid:
            continue
        booked_not_settled = (
            BreakKind.CASH_MISSING_AT_CUSTODIAN.value in p.break_kinds
            and BreakKind.CASH_MISSING_IN_BOOK.value not in p.break_kinds
        )
        if booked_not_settled:
            p.resolved_category = Category.TIMING
            p.clear_reason = f"Custodian settled the booked trade on {as_of}: resolved as a late settlement."
        else:
            p.resolved_category = current_category(p)
            p.clear_reason = f"No break on {as_of}: book and custodian agree again."
        p.cleared_on = str(as_of)
        p.age_days = business_days_between(date.fromisoformat(p.first_seen), as_of)
        cleared.append(p)
        _audit(audit, actor, role, "CASE_AUTO_CLEARED", {
            "case_id": p.case_id, "security_id": p.security_id, "first_seen": p.first_seen,
            "days_open": p.age_days, "suggested": p.category.value,
            "resolved_as": p.resolved_category.value, "reason": p.clear_reason,
        })

    open_cases: list[Case] = []
    for t in today_cases:
        t.break_kinds = sorted({kinds[b] for b in t.break_ids if b in kinds})
        p = prior_by_sid.get(t.security_id)
        if p is None:
            t.first_seen = str(as_of)
        else:
            t.case_id = p.case_id
            t.first_seen = p.first_seen
            t.escalated, t.escalation_reason = p.escalated, p.escalation_reason
            t.sla_breached = p.sla_breached
            if p.status != "PENDING" and p.category is t.category:
                t.status, t.final_category = p.status, p.final_category
                t.reviewed_by, t.reviewed_role, t.review_note = p.reviewed_by, p.reviewed_role, p.review_note
            elif p.status != "PENDING":
                _audit(audit, actor, role, "CASE_REOPENED", {
                    "case_id": t.case_id, "was": p.category.value, "now": t.category.value,
                    "previous_decision": p.status,
                })

        t.age_days = business_days_between(date.fromisoformat(t.first_seen), as_of)
        t.age_bucket = age_bucket(t.age_days)
        t.sla_days = settings.sla_days_material if t.material else settings.sla_days_other

        reasons = []
        if t.material:
            reasons.append(f"material ({t.nav_impact_bp:+.2f} bp of NAV)")
        if t.age_days > settings.escalate_after_days:
            reasons.append(f"aged: open {t.age_days} business days")
        # Each reason is recorded once; its first word ("material", "aged") identifies it.
        new = [r for r in reasons if r.split(" ")[0].rstrip(":") not in t.escalation_reason]
        if new:
            t.escalated = True
            t.escalation_reason = "; ".join(filter(None, [t.escalation_reason, *new]))
            _audit(audit, actor, role, "CASE_ESCALATED", {
                "case_id": t.case_id, "reasons": new, "nav_impact": t.nav_impact, "age_days": t.age_days,
            })

        if t.age_days > t.sla_days and not t.sla_breached:
            t.sla_breached = True
            _audit(audit, actor, role, "SLA_BREACHED", {
                "case_id": t.case_id, "age_days": t.age_days, "sla_days": t.sla_days, "material": t.material,
            })
        open_cases.append(t)
    return open_cases, cleared


# --------------------------------------------------------------------------- persistence


def snapshot_dir(run: str | Path, as_of: date | str) -> Path:
    return Path(run) / STATE_DIR / str(as_of)


def snapshot_dates(run: str | Path) -> list[date]:
    root = Path(run) / STATE_DIR
    if not root.exists():
        return []
    out = []
    for p in root.iterdir():
        try:
            if (p / "ledger.json").exists():
                out.append(date.fromisoformat(p.name))
        except ValueError:
            continue
    return sorted(out)


def latest_before(run: str | Path, as_of: date) -> date | None:
    earlier = [d for d in snapshot_dates(run) if d < as_of]
    return earlier[-1] if earlier else None


def load_ledger(run: str | Path, as_of: date | str) -> list[Case]:
    return load_cases(snapshot_dir(run, as_of) / "ledger.json")


def save_ledger(run: str | Path, as_of: date | str, cases: list[Case]) -> None:
    folder = snapshot_dir(run, as_of)
    folder.mkdir(parents=True, exist_ok=True)
    save_cases(cases, folder / "ledger.json")


def save_open_items(run: str | Path, as_of: date, recon: ReconResult) -> None:
    book, cust = carry_forward(recon)
    folder = snapshot_dir(run, as_of)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "book": [{**asdict(i), "origin_date": str(i.origin_date)} for i in book],
        "custodian": [{**asdict(c), "value_date": str(c.value_date)} for c in cust],
    }
    (folder / "open_items.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_open_items(run: str | Path, as_of: date) -> tuple[list[CarriedItem], list[CashLine]]:
    path = snapshot_dir(run, as_of) / "open_items.json"
    if not path.exists():
        return [], []
    raw = json.loads(path.read_text(encoding="utf-8"))
    book = [CarriedItem(r["reference"], r["security_id"], r["amount"], date.fromisoformat(r["origin_date"]))
            for r in raw["book"]]
    cust = [CashLine(r["entry_id"], date.fromisoformat(r["value_date"]), r["security_id"], r["reference"],
                     r["description"], r["amount"]) for r in raw["custodian"]]
    return book, cust


def update_ledger_cases(run: str | Path, as_of: date | str, changed: list[Case]) -> None:
    """Write review decisions back into the day's ledger snapshot."""
    ledger = load_ledger(run, as_of)
    by_id = {c.case_id: c for c in changed}
    save_ledger(run, as_of, [by_id.get(c.case_id, c) for c in ledger])
