"""The schema: tables, the application role, the append-only audit log and the instance mode."""

from __future__ import annotations

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, make_url, text

from reconpilot_web import cli, db
from reconpilot_web.models import Base, assert_instance_mode, get_instance_mode

from .conftest import make_settings

TABLES = {
    "instance_settings",
    "users",
    "sessions",
    "funds",
    "business_days",
    "input_files",
    "cases",
    "case_snapshots",
    "breaks",
    "open_items",
    "decisions",
    "audit_log",
    "jobs",
    "ai_cache",
    "unlock_requests",
}

INSERT_AUDIT = (
    "INSERT INTO audit_log (seq, ts, actor, role, action, payload, prev_hash, hash) "
    "VALUES (%s, '2026-11-13T09:00:00+00:00', 'priya', 'analyst', 'TEST', '{}', %s, %s)"
)

CHANGES = (
    "UPDATE audit_log SET actor = 'mallory'",
    "DELETE FROM audit_log",
    "TRUNCATE audit_log",
)


def _libpq(uri: str) -> str:
    """A URI psycopg can open directly (no SQLAlchemy driver suffix)."""
    return make_url(uri).set(drivername="postgresql").render_as_string(hide_password=False)


def test_all_tables_exist(db_engine, clean_db):
    names = set(inspect(db_engine).get_table_names())
    assert names == TABLES | {"alembic_version"}


def test_models_match_migration(db_engine, clean_db):
    with db_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_keys_and_constraints(db_engine, clean_db):
    insp = inspect(db_engine)
    assert insp.get_pk_constraint("cases")["constrained_columns"] == ["fund_id", "case_id"]
    assert insp.get_pk_constraint("case_snapshots")["constrained_columns"] == ["fund_id", "case_id", "as_of"]
    assert any(u["column_names"] == ["fund_id", "as_of"] for u in insp.get_unique_constraints("business_days"))
    assert any(u["column_names"] == ["seq"] for u in insp.get_unique_constraints("audit_log"))
    jobs = {c["name"]: c for c in insp.get_columns("jobs")}
    assert "3" in str(jobs["max_attempts"]["default"])
    assert {"version", "data"} <= {c["name"] for c in insp.get_columns("cases")}


def test_job_status_is_constrained(db_session):
    with pytest.raises(Exception, match="jobs_status"):
        db_session.execute(text("INSERT INTO jobs (kind, status) VALUES ('run_day', 'paused')"))


def test_app_role_cannot_update_audit_log(db_session, app_db_uri):
    with psycopg.connect(_libpq(app_db_uri)) as conn:
        conn.execute(INSERT_AUDIT, (1, "0" * 64, "a" * 64))
        conn.commit()
        assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 1
        for statement in CHANGES:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)
            conn.rollback()
        assert conn.execute("SELECT actor FROM audit_log").fetchone()[0] == "priya"


def test_app_role_can_write_other_tables(db_session, app_db_uri):
    with psycopg.connect(_libpq(app_db_uri)) as conn:
        user_id = conn.execute(
            "INSERT INTO users (username, role) VALUES ('priya', 'analyst') RETURNING id"
        ).fetchone()[0]
        conn.execute("UPDATE users SET display_name = 'Priya' WHERE id = %s", (user_id,))
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()


def test_app_role_cannot_change_instance_mode(db_session, app_db_uri):
    with psycopg.connect(_libpq(app_db_uri)) as conn:
        assert conn.execute("SELECT mode FROM instance_settings").fetchone()[0] == "real"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE instance_settings SET mode = 'demo'")


def test_superuser_cannot_update_audit_log_either(db_session, pg_uri):
    with psycopg.connect(_libpq(pg_uri)) as conn:
        conn.execute(INSERT_AUDIT, (1, "0" * 64, "a" * 64))
        conn.commit()
        for statement in CHANGES:
            with pytest.raises(psycopg.Error, match="audit_log is append-only"):
                conn.execute(statement)
            conn.rollback()
        assert conn.execute("SELECT actor FROM audit_log").fetchone()[0] == "priya"


def test_instance_mode_written_once(db_session, settings):
    assert get_instance_mode(db_session) == "real"
    assert cli.migrate(settings) == "real"  # running migrate again is harmless
    assert db_session.execute(text("SELECT count(*) FROM instance_settings")).scalar_one() == 1


def test_instance_mode_mismatch_refused(db_session, pg_uri, pg_dir):
    assert_instance_mode(db_session, "real")
    with pytest.raises(RuntimeError) as err:
        assert_instance_mode(db_session, "demo")
    assert str(err.value) == "database is a real database; this instance runs in demo mode"
    with pytest.raises(RuntimeError, match="real database"):
        cli.migrate(make_settings(pg_uri, pg_dir, mode="demo"))
    db_session.rollback()
    assert get_instance_mode(db_session) == "real"


def test_cli_migrate_refuses_other_mode(monkeypatch, capsys, clean_db, pg_uri, pg_dir):
    monkeypatch.setenv("RP_DATABASE_URL", pg_uri)
    monkeypatch.delenv("RP_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("RP_DATA_DIR", str(pg_dir))
    monkeypatch.setenv("RP_MODE", "demo")
    assert cli.main(["migrate"]) == 1
    assert "this instance runs in demo mode" in capsys.readouterr().err
    monkeypatch.setenv("RP_MODE", "real")
    assert cli.main(["migrate"]) == 0


def test_migration_downgrades_and_upgrades(pg_uri, migrated_db):
    """The initial revision can be removed and applied again on a fresh database."""
    admin = _libpq(pg_uri)
    scratch_name = "rp_migration_check"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {scratch_name}")
        conn.execute(f"CREATE DATABASE {scratch_name}")
    scratch = make_url(pg_uri).set(database=scratch_name).render_as_string(hide_password=False)
    try:
        cfg = cli.alembic_config(scratch)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        engine = db.make_engine(scratch)
        try:
            assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        finally:
            engine.dispose()
        command.upgrade(cfg, "head")
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {scratch_name} WITH (FORCE)")
