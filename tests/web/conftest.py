"""Fixtures for the web layer.

One embedded PostgreSQL serves the whole test session. The schema is migrated
once; every test that uses ``db_session`` (or ``clean_db``) starts from empty
tables, except ``instance_settings``, which keeps the mode written by ``migrate``.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text

from reconpilot_web import cli, db, devdb
from reconpilot_web.config import Settings, load_settings
from reconpilot_web.models import Base

APP_ROLE = "rp_app"
APP_PASSWORD = "rp_app_dev"

# Every test user's password unless a test says otherwise (long enough and not common).
TEST_PASSWORD = "Ledger-Walrus-4817"


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


# --------------------------------------------------------------------------- app, users, clients


@pytest.fixture
def app(clean_db, settings):
    from reconpilot_web.app import create_app

    application = create_app(settings)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def make_user(clean_db, db_engine):
    """``make_user(username, role="analyst", password=TEST_PASSWORD, is_admin=False)`` -> ``User``."""
    from reconpilot_web.auth import create_user

    def _make(username: str, role: str = "analyst", password: str = TEST_PASSWORD, is_admin: bool = False,
              display_name: str = ""):
        with db.SessionLocal(bind=db_engine) as session, session.begin():
            return create_user(session, username, password, role, is_admin=is_admin, display_name=display_name)

    return _make


@pytest.fixture
def users(make_user):
    """The four standard users: ``analyst1``, ``approver1``, ``approver2`` and ``viewer1``."""
    return {
        "analyst1": make_user("analyst1", "analyst", display_name="Priya Shah"),
        "approver1": make_user("approver1", "approver", display_name="Ann Lee"),
        "approver2": make_user("approver2", "approver", display_name="Tom Reed"),
        "viewer1": make_user("viewer1", "viewer", display_name="Vic Moss"),
    }


def sign_in(client: TestClient, username: str, password: str = TEST_PASSWORD) -> TestClient:
    """Sign ``client`` in and send the CSRF token on its later requests. Asserts success."""
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = client.cookies["rp_csrf"]
    return client


@pytest.fixture
def make_client(app):
    """``make_client(username=None)`` -> a new ``TestClient``, signed in as ``username`` if given."""
    clients: list[TestClient] = []

    def _make(username: str | None = None, password: str = TEST_PASSWORD) -> TestClient:
        c = TestClient(app)
        clients.append(c)
        return sign_in(c, username, password) if username else c

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def client(make_client) -> TestClient:
    """A signed-out client."""
    return make_client()


# --------------------------------------------------------------------------- funds and day files

FUND_CODE = "GEF1"
FUND_START = date(2026, 11, 9)  # a Monday


@pytest.fixture
def make_fund(clean_db, db_engine):
    """``make_fund(code=FUND_CODE, start_date=FUND_START, **kwargs)`` -> ``Fund`` (see ``funds.create_fund``)."""
    from reconpilot_web.funds import create_fund

    def _make(code: str = FUND_CODE, start_date: date = FUND_START, name: str = "Global Equity Fund",
              **kwargs):
        with db.SessionLocal(bind=db_engine, expire_on_commit=False) as session, session.begin():
            return create_fund(session, code, name, start_date, **kwargs)

    return _make


@pytest.fixture
def fund(make_fund):
    return make_fund()


@pytest.fixture(scope="session")
def day_files(tmp_path_factory) -> list[dict[str, bytes]]:
    """Three generated business days from ``FUND_START`` as ``{kind: bytes}`` (no ``truth`` file).

    Made with the engine's own sequence generator and ``storage.write_day``, so
    the bytes are exactly what the command line reads.
    """
    from reconpilot.sequence import generate_sequence
    from reconpilot.storage import write_day
    from reconpilot_web.validation import FILE_KINDS

    root = tmp_path_factory.mktemp("days")
    out = []
    for day, truth in generate_sequence(FUND_START, 3, 4, seed=11):
        folder = write_day(day, root / str(day.as_of), truth)
        out.append({kind: (folder / name).read_bytes() for kind, name in FILE_KINDS.items()})
    return out
