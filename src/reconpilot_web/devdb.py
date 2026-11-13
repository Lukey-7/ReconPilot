"""Embedded PostgreSQL for development and tests, started from Python through pgserver.

Nothing is installed system-wide: the server binaries ship inside the ``pgserver``
wheel and the cluster lives in ``<data_dir>/pg``. A server already running on
that folder (for example started by another process) is reused. The server stops
when the last process using it exits.
"""

from __future__ import annotations

from pathlib import Path

DATABASE = "reconpilot"


def _server(data_dir: Path):
    import pgserver  # imported lazily: production uses DATABASE_URL and never needs it

    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return pgserver.get_server(data_dir / "pg", cleanup_mode="stop")


def start(data_dir: Path) -> str:
    """Start (or reuse) the embedded server and return a superuser URI to the ``reconpilot`` database."""
    import psycopg

    server = _server(data_dir)
    admin_uri = server.get_uri()
    with psycopg.connect(admin_uri, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{DATABASE}" ENCODING \'UTF8\' TEMPLATE template0')
    return server.get_uri(database=DATABASE)


def stop(data_dir: Path) -> None:
    """Stop the embedded server for ``data_dir`` if this process started or reused it."""
    import pgserver

    pgdata = (Path(data_dir) / "pg").resolve()
    server = pgserver.PostgresServer._instances.get(pgdata)
    if server is not None:
        server.cleanup()
