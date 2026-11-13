"""The engine's hash-chained audit log, written to PostgreSQL (spec section 8).

``DbAuditLog`` has the engine ``AuditLog``'s ``append(actor, role, action,
payload)``, so the engine's review, ledger and AI code write to it unchanged.
Each record has the engine's fields (``seq``, ``ts``, ``actor``, ``role``,
``action``, ``payload``, ``prev_hash``) and its ``hash`` is
``reconpilot.audit.record_hash`` of them, so a chain exported from the database
verifies exactly like an ``audit.jsonl`` file.

Appends are serialised with a transaction-level advisory lock, so two requests
can never read the same previous hash and fork the chain. The lock is held
until the caller's transaction ends: an entry is part of the caller's work and
disappears with it on rollback, and the next writer sees it only once it is
committed. The chain is global (one per database); ``fund_id`` and ``case_id``
are copied into their own columns for filtering and are not part of the hash.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from reconpilot.audit import GENESIS, record_hash
from reconpilot_web.models import AuditEntry

AUDIT_LOCK_KEY = 727274  # pg_advisory_xact_lock key that serialises appends

RECORD_FIELDS = ("seq", "ts", "actor", "role", "action", "payload", "prev_hash", "hash")


def _json_safe(value: Any) -> Any:
    """``value`` as plain JSON types, the way the engine's hash sees it (``default=str``).

    Non-finite floats become strings because PostgreSQL's JSONB cannot hold them.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.loads(json.dumps(value, default=str))


def _record(entry: AuditEntry) -> dict:
    return {
        "seq": entry.seq,
        "ts": entry.ts,
        "actor": entry.actor,
        "role": entry.role,
        "action": entry.action,
        "payload": entry.payload,
        "prev_hash": entry.prev_hash,
        "hash": entry.hash,
    }


class DbAuditLog:
    """An engine-compatible audit log over the ``audit_log`` table.

    Writes go into ``session``'s current transaction; the caller commits or rolls back.
    ``fund_id`` tags every entry this log writes and is the default filter for ``entries``.
    """

    def __init__(self, session: Session, fund_id: int | None = None):
        self.session = session
        self.fund_id = fund_id

    def append(self, actor: str, role: str, action: str, payload: dict | None = None) -> dict:
        session = self.session
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": AUDIT_LOCK_KEY})
        last = session.execute(
            select(AuditEntry.seq, AuditEntry.hash).order_by(AuditEntry.seq.desc()).limit(1)
        ).first()
        body = _json_safe(payload or {})
        record = {
            "seq": (last.seq if last else 0) + 1,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor": str(actor),
            "role": str(role),
            "action": str(action),
            "payload": body,
            "prev_hash": last.hash if last else GENESIS,
        }
        record["hash"] = record_hash(record)
        case_id = body.get("case_id") if isinstance(body, dict) else None
        session.add(
            AuditEntry(
                **record,
                fund_id=self.fund_id,
                case_id=case_id if isinstance(case_id, str) else None,
            )
        )
        session.flush()
        return record

    def entries(self, fund_id: int | None = None) -> list[dict]:
        """Records in chain order: those of ``fund_id`` (default: this log's fund), or all if neither is set."""
        fund = fund_id if fund_id is not None else self.fund_id
        query = select(AuditEntry).order_by(AuditEntry.seq)
        if fund is not None:
            query = query.where(AuditEntry.fund_id == fund)
        return [_record(e) for e in self.session.execute(query).scalars()]

    def verify(self) -> tuple[bool, int | None]:
        """The whole chain, as the engine's ``AuditLog.verify``."""
        return verify_chain(self.session)


def verify_chain(session: Session) -> tuple[bool, int | None]:
    """Re-check every hash in the database.

    Returns ``(True, None)`` when the chain is intact, else ``(False, seq)`` where ``seq``
    is the position of the first entry that does not fit (a gap, a wrong previous hash or
    a wrong hash), as the engine's ``AuditLog.verify`` reports it.
    """
    prev = GENESIS
    expected = 1
    rows = session.execute(
        select(
            AuditEntry.seq,
            AuditEntry.ts,
            AuditEntry.actor,
            AuditEntry.role,
            AuditEntry.action,
            AuditEntry.payload,
            AuditEntry.prev_hash,
            AuditEntry.hash,
        )
        .order_by(AuditEntry.seq)
        .execution_options(yield_per=1000)
    )
    for row in rows:
        body = {
            "seq": row.seq,
            "ts": row.ts,
            "actor": row.actor,
            "role": row.role,
            "action": row.action,
            "payload": row.payload,
            "prev_hash": row.prev_hash,
        }
        if row.seq != expected or row.prev_hash != prev or record_hash(body) != row.hash:
            return False, expected
        prev = row.hash
        expected += 1
    return True, None
