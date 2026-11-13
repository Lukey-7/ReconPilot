"""Append-only, tamper-evident audit log.

Each entry is one JSON line holding the SHA-256 hash of the previous entry,
so editing, deleting or reordering any line breaks the chain from that point
on. ``verify`` walks the file and reports the first entry that does not fit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _digest(record: dict) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def append(self, actor: str, role: str, action: str, payload: dict | None = None) -> dict:
        existing = self.entries()
        prev = existing[-1]["hash"] if existing else GENESIS
        record = {
            "seq": len(existing) + 1,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor": actor,
            "role": role,
            "action": action,
            "payload": payload or {},
            "prev_hash": prev,
        }
        record["hash"] = _digest(record)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return record

    def verify(self) -> tuple[bool, int | None]:
        """Return (True, None) if the chain is intact, else (False, seq of first bad entry)."""
        prev = GENESIS
        for i, entry in enumerate(self.entries(), start=1):
            body = {k: v for k, v in entry.items() if k != "hash"}
            if entry.get("seq") != i or entry.get("prev_hash") != prev or _digest(body) != entry.get("hash"):
                return False, i
            prev = entry["hash"]
        return True, None
