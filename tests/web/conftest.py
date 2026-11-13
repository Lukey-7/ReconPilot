"""Fixtures for the web layer.

One embedded PostgreSQL serves the whole test session. The schema is migrated
once; every test that uses ``db_session`` (or ``clean_db``) starts from empty
tables, except ``instance_settings``, which keeps the mode written by ``migrate``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import make_url, text

from reconpilot_web import cli, db, devdb
from reconpilot_web.config import Settings, load_settings
from reconpilot_web.models import Base

APP_ROLE = "rp_app"
APP_PASSWORD = "rp_app_dev"


def make_settings(pg_uri: str, data_dir, mode: str = "real") -> Settings:
    return load_settings(
        {
            "RP_DATABASE_URL": pg_uri,
            "RP_MIGRATION_DATABASE_URL": pg_uri,
            "RP_MODE": mode,
            "RP_DATA_DIR": str(data_dir),
        }
    )


@pytest.fixture(scope="session")
def pg_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("rp_data")


@pytest.fixture(scope="session")
def pg_uri(pg_dir):
    """Superuser URI for an embedded server that lives for the whole test session."""
    uri = devdb.start(pg_dir)
    yield uri
    devdb.stop(pg_dir)


@pytest.fixture(scope="session")
def db_engine(pg_uri):
    engine = db.make_engine(pg_uri)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_db(pg_uri, pg_dir):
    """Run ``reconpilot-web migrate`` once for the session (mode ``real``)."""
    cli.migrate(make_settings(pg_uri, pg_dir))
    return pg_uri


@pytest.fixture(scope="session")
def app_db_uri(pg_uri, migrated_db):
    """URI for the application role ``rp_app`` created by the migration."""
    url = make_url(pg_uri).set(username=APP_ROLE, password=APP_PASSWORD)
    return url.render_as_string(hide_password=False)


def truncate_all(engine) -> None:
    """Empty every table except ``instance_settings``, the audit log included."""
    names = [t.name for t in Base.metadata.sorted_tables if t.name != "instance_settings"]
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
        conn.execute(text(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE"))
        conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))


@pytest.fixture
def clean_db(migrated_db, db_engine):
    truncate_all(db_engine)
    return migrated_db


@pytest.fixture
def settings(pg_uri, pg_dir) -> Settings:
    return make_settings(pg_uri, pg_dir)


@pytest.fixture
def db_session(clean_db, db_engine):
    session = db.SessionLocal(bind=db_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
