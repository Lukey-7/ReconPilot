"""The ``reconpilot-web`` command line."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import date
from pathlib import Path

from reconpilot_web.config import Settings, load_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def database_urls(settings: Settings) -> tuple[str, str]:
    """``(app_url, migration_url)``; with no ``RP_DATABASE_URL`` both point at the embedded server."""
    if settings.database_url:
        return settings.database_url, settings.migration_database_url or settings.database_url
    from reconpilot_web import devdb

    uri = devdb.start(settings.data_dir)
    return uri, uri


def alembic_config(url: str):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["url"] = url
    return cfg


def migrate(settings: Settings) -> str:
    """Bring the schema to the latest revision and record (or check) the instance mode.

    Returns the instance mode. Raises ``RuntimeError`` if the database was written
    for the other mode, so demo and real data can never share a database.
    """
    from alembic import command

    from reconpilot_web import db
    from reconpilot_web.models import ensure_instance_mode

    _, url = database_urls(settings)
    command.upgrade(alembic_config(url), "head")
    engine = db.make_engine(url)
    try:
        with db.SessionLocal(bind=engine) as session, session.begin():
            ensure_instance_mode(session, settings.mode)
    finally:
        engine.dispose()
    return settings.mode


def _cmd_migrate(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        mode = migrate(settings)
    except RuntimeError as exc:
        print(f"reconpilot-web: {exc}", file=sys.stderr)
        return 1
    print(f"Database schema is up to date ({mode} mode).")
    return 0


def _read_new_password() -> str:
    """The new user's password from ``RP_NEW_PASSWORD``, else typed twice at a prompt."""
    password = os.environ.get("RP_NEW_PASSWORD")
    if password:
        return password
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise ValueError("The two passwords differ.")
    return first


def create_user(settings: Settings, username: str, password: str, role: str,
                is_admin: bool = False, display_name: str = "") -> None:
    """Add a user to the configured database (audited as ``USER_CREATED``)."""
    from reconpilot_web import auth, db
    from reconpilot_web.models import assert_instance_mode

    url, _ = database_urls(settings)
    engine = db.make_engine(url)
    try:
        with db.SessionLocal(bind=engine) as session, session.begin():
            assert_instance_mode(session, settings.mode)
            auth.create_user(session, username, password, role, is_admin=is_admin, display_name=display_name)
    finally:
        engine.dispose()


def _cmd_create_user(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        password = _read_new_password()
        create_user(settings, args.username, password, args.role, args.admin, args.display_name)
    except (ValueError, RuntimeError) as exc:
        print(f"reconpilot-web: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.role} {args.username}{' (admin)' if args.admin else ''}.")
    return 0


def create_fund(settings: Settings, code: str, name: str, start_date: date,
                base_currency: str = "USD", non_business_dates: list[date] | None = None) -> None:
    """Add a fund to the configured database (audited as ``FUND_CREATED``)."""
    from reconpilot_web import db, funds
    from reconpilot_web.models import assert_instance_mode

    url, _ = database_urls(settings)
    engine = db.make_engine(url)
    try:
        with db.SessionLocal(bind=engine) as session, session.begin():
            assert_instance_mode(session, settings.mode)
            funds.create_fund(session, code, name, start_date, base_currency=base_currency,
                              non_business_dates=non_business_dates or ())
    finally:
        engine.dispose()


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date in YYYY-MM-DD form: {value!r}") from None


def _cmd_create_fund(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        create_fund(settings, args.code, args.name, args.start_date, args.base_currency, args.non_business_date)
    except (ValueError, RuntimeError) as exc:
        print(f"reconpilot-web: {exc}", file=sys.stderr)
        return 1
    print(f"Created fund {args.code.strip().upper()} starting {args.start_date}.")
    return 0


def _cmd_worker(args: argparse.Namespace) -> int:
    import logging

    from reconpilot_web.jobs import run_worker

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
        done = run_worker(settings, once=args.once)
    except (ValueError, RuntimeError) as exc:
        print(f"reconpilot-web: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Worker stopped.")
        return 0
    if args.once:
        print(f"Ran {done} job(s); the queue is empty.")
    return 0


# --------------------------------------------------------------------------- serving

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# What ``dev`` creates in an empty database: one fund and one user per role.
DEV_FUND_CODE = "DEMO1"
DEV_FUND_NAME = "Demo Global Equity Fund"
DEV_START_DATE = date(2026, 11, 9)  # a Monday: generate days from here with ``reconpilot generate``
DEV_USERS: tuple[tuple[str, str, bool, str], ...] = (
    # username, role, admin, display name
    ("analyst1", "analyst", False, "Analyst One"),
    ("approver1", "approver", True, "Approver One"),
    ("approver2", "approver", False, "Approver Two"),
    ("viewer1", "viewer", False, "Viewer One"),
)


def one_time_password() -> str:
    """A random password that meets the password policy, for a user to sign in with first."""
    import secrets

    from reconpilot_web.security import check_password_policy

    while True:
        password = secrets.token_urlsafe(15)  # 20 characters
        if not check_password_policy(password):
            return password


def dev_bootstrap(session, start_date: date = DEV_START_DATE) -> dict[str, str]:
    """Give an empty database the development fund and users, in ``session``'s transaction.

    Returns ``{username: one-time password}`` for the users created, or ``{}`` when
    the database already has a user or a fund (nothing is touched then).
    """
    from sqlalchemy import select

    from reconpilot_web import auth, funds
    from reconpilot_web.models import Fund, User

    if session.execute(select(User.id).limit(1)).first() or session.execute(select(Fund.id).limit(1)).first():
        return {}
    funds.create_fund(session, DEV_FUND_CODE, DEV_FUND_NAME, start_date)
    created: dict[str, str] = {}
    for username, role, is_admin, display_name in DEV_USERS:
        password = one_time_password()
        auth.create_user(session, username, password, role, is_admin=is_admin, display_name=display_name)
        created[username] = password
    return created


def _serve_api(settings: Settings, host: str, port: int) -> None:
    import uvicorn

    from reconpilot_web.app import create_app

    uvicorn.run(create_app(settings), host=host, port=port, log_level="info")


def _cmd_dev(args: argparse.Namespace) -> int:
    """Embedded database, migrations, first-run fund and users, then the API and a worker thread."""
    import logging
    import signal
    import threading

    from reconpilot_web import db
    from reconpilot_web.jobs import run_worker

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("pgserver", "alembic"):  # their INFO lines are start-up chatter, not news
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        settings = load_settings()
        url, _ = database_urls(settings)  # starts (or reuses) the embedded server when no URL is set
        mode = migrate(settings)
        engine = db.make_engine(url)
        try:
            with db.SessionLocal(bind=engine) as session, session.begin():
                created = dev_bootstrap(session, args.start_date)
        finally:
            engine.dispose()
    except (ValueError, RuntimeError) as exc:
        print(f"reconpilot-web: {exc}", file=sys.stderr)
        return 1

    where = "RP_DATABASE_URL" if settings.database_url else f"the embedded database in {settings.data_dir}"
    print(f"Database: {where} ({mode} mode), schema up to date.")
    if created:
        print(f"Created fund {DEV_FUND_CODE} starting {args.start_date} and these users. "
              "The passwords are shown once only; note them now:")
        for username, role, is_admin, _ in DEV_USERS:
            print(f"  {username:<10} {role:<9}{' admin' if is_admin else '      '}  {created[username]}")

    if hasattr(signal, "SIGBREAK"):  # Windows: let Ctrl+Break stop everything as tidily as Ctrl+C
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    stop = threading.Event()
    worker = threading.Thread(target=run_worker, args=(settings,), kwargs={"stop": stop},
                              name="reconpilot-worker", daemon=True)
    worker.start()
    print(f"API on http://{args.host}:{args.port}/api with a worker running in-process. Ctrl+C stops everything.")
    try:
        _serve_api(settings, args.host, args.port)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join(timeout=30)
    print("Stopped.")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        _serve_api(settings, args.host, args.port)
    except (ValueError, RuntimeError) as exc:
        print(f"reconpilot-web: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def _add_listen_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", default=DEFAULT_HOST, help=f"address to listen on (default {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to listen on (default {DEFAULT_PORT})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconpilot-web",
        description="Run the ReconPilot web application.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser(
        "dev",
        help="run everything for development: database, migrations, API and worker",
        description="Start the embedded PostgreSQL in RP_DATA_DIR (or use RP_DATABASE_URL), bring the "
        f"schema up to date and, if the database is empty, create the fund {DEV_FUND_CODE} and the users "
        f"{', '.join(u[0] for u in DEV_USERS)} with one-time passwords printed once. Then serve the API "
        "with a worker running in the same process. Ctrl+C stops everything.",
    )
    _add_listen_args(p)
    p.add_argument("--start-date", type=_iso_date, default=DEV_START_DATE,
                   help=f"first business day of {DEV_FUND_CODE} when it is created (default {DEV_START_DATE})")
    p.set_defaults(func=_cmd_dev)

    p = sub.add_parser(
        "serve",
        help="serve the API only (run the worker separately)",
        description="Serve the API against RP_DATABASE_URL (or the embedded database). Run "
        "'reconpilot-web migrate' first and 'reconpilot-web worker' alongside to run days.",
    )
    _add_listen_args(p)
    p.set_defaults(func=_cmd_serve)

    p = sub.add_parser(
        "migrate",
        help="create or upgrade the database schema and record the instance mode",
        description="Create or upgrade the database schema. The first run records RP_MODE "
        "(real or demo) in the database; later runs refuse a different mode.",
    )
    p.set_defaults(func=_cmd_migrate)

    p = sub.add_parser(
        "create-user",
        help="add a user account",
        description="Add a user. The password is read from RP_NEW_PASSWORD or typed at a prompt; "
        "it needs at least 12 characters and must not be a common password.",
    )
    p.add_argument("--username", required=True)
    p.add_argument("--role", required=True, choices=("analyst", "approver", "viewer"))
    p.add_argument("--admin", action="store_true", help="allow user and fund administration")
    p.add_argument("--display-name", default="", help="name shown in the app (default: the username)")
    p.set_defaults(func=_cmd_create_user)

    p = sub.add_parser(
        "create-fund",
        help="add a fund",
        description="Add a fund with the engine's default settings. Its business days are the weekdays "
        "from the start date on, less any non-business dates.",
    )
    p.add_argument("--code", required=True, help="short fund code used in URLs, for example GEF1")
    p.add_argument("--name", required=True)
    p.add_argument("--start-date", required=True, type=_iso_date, help="the fund's first business day (YYYY-MM-DD)")
    p.add_argument("--base-currency", default="USD")
    p.add_argument("--non-business-date", action="append", type=_iso_date, default=[], metavar="DATE",
                   help="a holiday (YYYY-MM-DD); repeat for several")
    p.set_defaults(func=_cmd_create_fund)

    p = sub.add_parser(
        "worker",
        help="run queued jobs (day runs)",
        description="Claim and run jobs from the database queue until stopped with Ctrl+C. "
        "A failed job is retried up to three times before it is marked failed.",
    )
    p.add_argument("--once", action="store_true", help="run every job that is due, then exit")
    p.set_defaults(func=_cmd_worker)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
