"""The ``reconpilot-web`` command line."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconpilot-web",
        description="Run the ReconPilot web application.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

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
