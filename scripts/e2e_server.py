"""The whole application for the browser tests (Playwright), on a throwaway embedded database.

``serve`` wipes ``--data-dir``, starts an embedded PostgreSQL in it, migrates, creates two
funds and the four standard users with a known test password, writes generated business
days (the engine's own sequence generator) to ``<data-dir>/days/<as_of>/`` for the tests
to upload through the browser (to either fund: they share a start date), then serves the API and the built front end (``web/dist``)
with a worker thread, as ``reconpilot-web dev`` does. Nothing is shared with a developer's
own ``.rp_data``.

``serve-demo`` does the same for the public demo's journey: a fresh embedded database in
``--data-dir`` served exactly as ``reconpilot-web serve --mode demo`` serves it (migrated in
demo mode, the AI cache loaded, a worker and the cleanup job in-process), with no users or
funds: visitors make their own.

``stop`` ends a ``serve`` (or ``serve-demo``) still running on ``--data-dir`` (its process id is kept in
``<data-dir>/server.pid``), then stops its embedded PostgreSQL, which would otherwise be
left running: Playwright ends its web server by killing it, so ``serve`` never gets to
stop the database itself.

    python scripts/e2e_server.py serve --data-dir <dir> --port 8765
    python scripts/e2e_server.py serve-demo --data-dir <dir> --port 8766
    python scripts/e2e_server.py stop --data-dir <dir>
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import threading
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FUND_CODE = "E2E1"
FUND_NAME = "End-to-End Test Fund"
# A second fund, for switching funds and for the upload screen's own journeys.
SECOND_FUND_CODE = "E2E2"
SECOND_FUND_NAME = "Second Test Fund"
START_DATE = date(2026, 11, 9)  # a Monday
DAYS = 2
BREAKS_PER_DAY = 5
# Seed 3's first day has four ordinary cases and one material, escalated case, and no failed
# check other than the material case itself: an analyst, an approver and a second approver
# can take it all the way to sign-off.
SEED = 3

# Test users only, on a database that is deleted before every run. Override with RP_E2E_PASSWORD.
DEFAULT_PASSWORD = "Ledger-Walrus-4817"
USERS: tuple[tuple[str, str, str], ...] = (
    ("analyst1", "analyst", "Analyst One"),
    ("approver1", "approver", "Approver One"),
    ("approver2", "approver", "Approver Two"),
    ("viewer1", "viewer", "Viewer One"),
)
# An administrator (an analyst by role), for the administration and unlocking journeys.
ADMINS: tuple[tuple[str, str, str], ...] = (("admin1", "analyst", "Admin One"),)


def write_days(folder: Path) -> list[Path]:
    """Generate the business days and write each day's CSV files (no answer key)."""
    from reconpilot.sequence import generate_sequence
    from reconpilot.storage import write_day

    return [write_day(day, folder / str(day.as_of))
            for day, _truth in generate_sequence(START_DATE, DAYS, BREAKS_PER_DAY, seed=SEED)]


def stop_server(data_dir: Path) -> None:
    """End the ``serve`` process recorded in ``<data_dir>/server.pid``, and its children."""
    import psutil  # a dependency of pgserver

    pid_file = data_dir.resolve() / "server.pid"
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        return
    try:
        server = psutil.Process(pid)
        processes = [server, *server.children(recursive=True)]
    except psutil.Error:
        return
    for process in processes:
        try:
            process.terminate()
        except psutil.Error:
            pass
    psutil.wait_procs(processes, timeout=10)
    pid_file.unlink(missing_ok=True)


def stop_database(data_dir: Path) -> None:
    """Stop an embedded PostgreSQL running on ``<data_dir>/pg``, if any."""
    from pgserver import pg_ctl

    pgdata = data_dir.resolve() / "pg"
    if (pgdata / "postmaster.pid").is_file():
        try:
            pg_ctl(["-w", "-m", "fast", "stop"], pgdata=pgdata)
        except Exception as exc:  # noqa: BLE001 - already stopped is fine
            print(f"e2e: could not stop PostgreSQL in {pgdata}: {exc}", file=sys.stderr)


def serve(data_dir: Path, host: str, port: int) -> int:
    from reconpilot_web import auth, cli, db, devdb, funds
    from reconpilot_web.config import load_settings
    from reconpilot_web.jobs import run_worker

    dist = cli.web_dist()
    if dist is None:
        print("e2e: no built front end in web/dist; run 'npm run build' in web/ first.", file=sys.stderr)
        return 1

    data_dir = data_dir.resolve()
    stop_server(data_dir)  # anything left behind by an earlier, killed run
    stop_database(data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "server.pid").write_text(str(os.getpid()))

    uri = devdb.start(data_dir)
    settings = load_settings({
        "RP_DATABASE_URL": uri,
        "RP_MIGRATION_DATABASE_URL": uri,
        "RP_MODE": "real",
        "RP_DATA_DIR": str(data_dir),
    })
    cli.migrate(settings)
    password = os.environ.get("RP_E2E_PASSWORD") or DEFAULT_PASSWORD
    engine = db.make_engine(uri)
    try:
        with db.SessionLocal(bind=engine) as session, session.begin():
            funds.create_fund(session, FUND_CODE, FUND_NAME, START_DATE)
            funds.create_fund(session, SECOND_FUND_CODE, SECOND_FUND_NAME, START_DATE)
            for username, role, display_name in USERS:
                auth.create_user(session, username, password, role, display_name=display_name)
            for username, role, display_name in ADMINS:
                auth.create_user(session, username, password, role, is_admin=True, display_name=display_name)
    finally:
        engine.dispose()
    written = write_days(data_dir / "days")
    print(f"e2e: funds {FUND_CODE} and {SECOND_FUND_CODE}, {len(USERS) + len(ADMINS)} users, days in {written[0].parent}",
          flush=True)

    stop = threading.Event()
    worker = threading.Thread(target=run_worker, args=(settings,), kwargs={"stop": stop, "poll_interval": 0.25},
                              name="reconpilot-worker", daemon=True)
    worker.start()
    try:
        import uvicorn

        from reconpilot_web.app import create_app

        uvicorn.run(create_app(settings, web_dist=dist), host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join(timeout=10)
        devdb.stop(data_dir)
    return 0


def fresh_data_dir(data_dir: Path) -> Path:
    """Stop anything an earlier, killed run left on ``data_dir``, then empty it."""
    data_dir = data_dir.resolve()
    stop_server(data_dir)
    stop_database(data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "server.pid").write_text(str(os.getpid()))
    return data_dir


def serve_demo(data_dir: Path, host: str, port: int) -> int:
    from reconpilot_web import cli, devdb
    from reconpilot_web.config import load_settings

    dist = cli.web_dist()
    if dist is None:
        print("e2e: no built front end in web/dist; run 'npm run build' in web/ first.", file=sys.stderr)
        return 1
    data_dir = fresh_data_dir(data_dir)
    uri = devdb.start(data_dir)
    settings = load_settings({
        "RP_DATABASE_URL": uri,
        "RP_MIGRATION_DATABASE_URL": uri,
        "RP_MODE": "demo",
        "RP_DATA_DIR": str(data_dir),
    })
    print(f"e2e: demo instance on {data_dir}", flush=True)
    try:
        cli.serve_demo(settings, host, port, dist, poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        devdb.stop(data_dir)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("serve", "serve-demo", "stop"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if args.command == "stop":
        stop_server(args.data_dir)
        stop_database(args.data_dir)
        return 0
    if args.command == "serve-demo":
        return serve_demo(args.data_dir, args.host, args.port)
    return serve(args.data_dir, args.host, args.port)


if __name__ == "__main__":
    sys.exit(main())
