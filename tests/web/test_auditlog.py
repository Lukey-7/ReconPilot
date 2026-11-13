"""The database audit log: engine format, chain verification, concurrency and rollback."""

from __future__ import annotations

import threading
from datetime import date

from sqlalchemy import create_engine, text

from reconpilot.audit import AuditLog, record_hash
from reconpilot_web import db
from reconpilot_web.auditlog import DbAuditLog, verify_chain
from reconpilot_web.models import AuditEntry


def test_append_matches_engine_format(db_session, tmp_path):
    engine_record = AuditLog(tmp_path / "audit.jsonl").append("priya", "analyst", "CASE_APPROVED", {"case_id": "C1"})
    record = DbAuditLog(db_session, fund_id=7).append(
        "priya", "analyst", "CASE_APPROVED", {"case_id": "C1", "as_of": date(2026, 11, 13)}
    )
    assert set(record) == set(engine_record)
    assert record["seq"] == 1 and record["prev_hash"] == "0" * 64
    assert record["hash"] == record_hash({k: v for k, v in record.items() if k != "hash"})
    assert record["payload"] == {"case_id": "C1", "as_of": "2026-11-13"}

    stored = db_session.query(AuditEntry).one()
    assert (stored.fund_id, stored.case_id, stored.hash) == (7, "C1", record["hash"])


def test_entries_in_order_and_filtered_by_fund(db_session):
    DbAuditLog(db_session, fund_id=1).append("priya", "analyst", "A")
    DbAuditLog(db_session, fund_id=2).append("ann", "approver", "B")
    DbAuditLog(db_session).append("system", "system", "C")
    assert [e["action"] for e in DbAuditLog(db_session).entries()] == ["A", "B", "C"]
    assert [e["action"] for e in DbAuditLog(db_session, fund_id=2).entries()] == ["B"]
    assert [e["seq"] for e in DbAuditLog(db_session).entries(fund_id=1)] == [1]


def test_chain_verifies(db_session):
    log = DbAuditLog(db_session, fund_id=1)
    assert verify_chain(db_session) == (True, None)
    for i in range(5):
        log.append("priya", "analyst", "STEP", {"i": i, "value": 1.25})
    db_session.commit()
    assert verify_chain(db_session) == (True, None)
    assert log.verify() == (True, None)
    entries = log.entries()
    assert [e["prev_hash"] for e in entries[1:]] == [e["hash"] for e in entries[:-1]]


def test_tamper_detected_via_superuser_bypass(db_session, db_engine):
    log = DbAuditLog(db_session)
    for i in range(4):
        log.append("priya", "analyst", "STEP", {"i": i})
    db_session.commit()
    with db_engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
        conn.execute(text("""UPDATE audit_log SET payload = '{"i": 99}' WHERE seq = 3"""))
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    db_session.expire_all()
    assert verify_chain(db_session) == (False, 3)


def test_concurrent_appends_keep_chain(clean_db, app_db_uri, db_session):
    engine = create_engine(db.sqlalchemy_url(app_db_uri), pool_size=20, max_overflow=5)  # one per thread
    errors: list[BaseException] = []
    start = threading.Barrier(20)

    def worker(n: int) -> None:
        try:
            start.wait()
            for i in range(10):
                with db.SessionLocal(bind=engine) as session, session.begin():
                    DbAuditLog(session, fund_id=n % 3).append(f"user{n}", "analyst", "STEP", {"n": n, "i": i})
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()

    assert errors == []
    seqs = [e["seq"] for e in DbAuditLog(db_session).entries()]
    assert seqs == list(range(1, 201))
    assert verify_chain(db_session) == (True, None)


def test_rollback_discards_entry(db_session):
    log = DbAuditLog(db_session)
    log.append("priya", "analyst", "KEPT")
    db_session.commit()
    log.append("priya", "analyst", "DISCARDED")
    db_session.rollback()
    assert [e["action"] for e in log.entries()] == ["KEPT"]
    record = log.append("priya", "analyst", "NEXT")
    assert record["seq"] == 2
    db_session.commit()
    assert verify_chain(db_session) == (True, None)


def test_chain_verifies_for_values_jsonb_rewrites(db_session):
    """-0.0 (from a rounded tiny negative impact) and whole floats >= 1e16 come back from JSONB in another form."""
    log = DbAuditLog(db_session, fund_id=1)
    payloads = [
        {"nav_impact": -0.0},
        {"v": 1e16},
        {"v": -1.5e16, "nested": [{"w": 1e300}, -0.0]},
        {"v": 1e-7, "w": 0.1 + 0.2, "x": 1.0, "y": float("nan")},
    ]
    records = [log.append("priya", "analyst", "CASE_ESCALATED", p) for p in payloads]
    db_session.commit()
    assert verify_chain(db_session) == (True, None)
    stored = [e["payload"] for e in log.entries()]
    assert [r["payload"] for r in records] == stored
    assert [r["hash"] for r in records] == [e["hash"] for e in log.entries()]
    for entry in log.entries():
        assert entry["hash"] == record_hash({k: v for k, v in entry.items() if k != "hash"})


def test_nul_characters_are_stored_and_chain_verifies(db_session):
    log = DbAuditLog(db_session)
    record = log.append("a\x00b", "analyst", "SIGN_IN_FAILED", {"username": "x\x00y", "k\x00": ["\x00"]})
    db_session.commit()
    assert record["actor"] == "a�b"
    assert record["payload"] == {"username": "x�y", "k�": ["�"]}
    assert verify_chain(db_session) == (True, None)
