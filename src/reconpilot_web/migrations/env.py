"""Alembic environment for the ReconPilot web database.

The database URL is taken, in order, from ``config.attributes["url"]`` (set by
``reconpilot_web.migrate``), the ``sqlalchemy.url`` option, or the settings
(``RP_MIGRATION_DATABASE_URL``, falling back to ``RP_DATABASE_URL``).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from reconpilot_web import models  # noqa: F401  (registers the tables on Base.metadata)
from reconpilot_web.config import load_settings
from reconpilot_web.db import Base, sqlalchemy_url

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("url") or config.get_main_option("sqlalchemy.url") or ""
    if not url:
        url = load_settings().migration_database_url
    if not url:
        raise RuntimeError("no database URL: set RP_MIGRATION_DATABASE_URL or RP_DATABASE_URL")
    return url


def run_migrations_offline() -> None:
    context.configure(url=sqlalchemy_url(_url()), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(sqlalchemy_url(_url()), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
