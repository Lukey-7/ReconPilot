"""Fixtures for the web layer: an embedded PostgreSQL per test session, settings and a session."""

from __future__ import annotations

import pytest

from reconpilot_web import db, devdb
from reconpilot_web.config import Settings, load_settings


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


@pytest.fixture
def settings(pg_uri, pg_dir) -> Settings:
    return load_settings(
        {
            "RP_DATABASE_URL": pg_uri,
            "RP_MIGRATION_DATABASE_URL": pg_uri,
            "RP_MODE": "real",
            "RP_DATA_DIR": str(pg_dir),
        }
    )


@pytest.fixture
def db_session(db_engine):
    session = db.SessionLocal(bind=db_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
