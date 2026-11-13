"""Settings from the environment and the embedded development database."""

from pathlib import Path

import pytest
from sqlalchemy import text

from reconpilot_web.config import load_settings
from reconpilot_web.db import sqlalchemy_url


def test_load_settings_defaults():
    s = load_settings({})
    assert s.database_url == ""
    assert s.migration_database_url == ""
    assert s.mode == "real"
    assert s.cookie_secure is False
    assert s.data_dir == Path(".rp_data")
    assert s.ai_cache_dir == Path(".rp_data") / "ai_cache"


def test_migration_url_defaults_to_database_url():
    s = load_settings({"RP_DATABASE_URL": "postgresql://app@db/rp", "RP_COOKIE_SECURE": "1", "RP_MODE": "demo"})
    assert s.migration_database_url == "postgresql://app@db/rp"
    assert s.cookie_secure is True
    assert s.mode == "demo"
    s = load_settings({"RP_DATABASE_URL": "postgresql://app@db/rp", "RP_MIGRATION_DATABASE_URL": "postgresql://owner@db/rp"})
    assert s.migration_database_url == "postgresql://owner@db/rp"


def test_load_settings_rejects_unknown_mode():
    with pytest.raises(ValueError):
        load_settings({"RP_MODE": "prod"})


def test_sqlalchemy_url_uses_psycopg():
    assert sqlalchemy_url("postgresql://u:@h:5/d") == "postgresql+psycopg://u:@h:5/d"
    assert sqlalchemy_url("postgres://u@h/d") == "postgresql+psycopg://u@h/d"
    assert sqlalchemy_url("postgresql+psycopg://u@h/d") == "postgresql+psycopg://u@h/d"


def test_devdb_starts_and_answers(db_session, pg_uri):
    assert pg_uri.endswith("/reconpilot")
    assert db_session.execute(text("select 1")).scalar_one() == 1
