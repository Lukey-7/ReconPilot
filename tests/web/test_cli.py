"""The ``reconpilot-web`` command line: the development bootstrap and the commands it offers."""

from __future__ import annotations

from sqlalchemy import select

from reconpilot_web import cli
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.models import Fund, User
from reconpilot_web.security import check_password_policy, verify_password


def test_dev_bootstrap_creates_fund_and_users_once(db_session):
    created = cli.dev_bootstrap(db_session)
    db_session.commit()
    assert sorted(created) == ["analyst1", "approver1", "approver2", "viewer1"]
    assert len(set(created.values())) == 4  # each user gets their own one-time password

    again = cli.dev_bootstrap(db_session)
    db_session.commit()
    assert again == {}

    funds = db_session.execute(select(Fund)).scalars().all()
    assert [(f.code, f.start_date) for f in funds] == [(cli.DEV_FUND_CODE, cli.DEV_START_DATE)]
    users = {u.username: u for u in db_session.execute(select(User)).scalars().all()}
    assert sorted(users) == sorted(created)
    assert {name: u.role for name, u in users.items()} == {
        "analyst1": "analyst", "approver1": "approver", "approver2": "approver", "viewer1": "viewer"}
    for name, password in created.items():
        assert check_password_policy(password) == []
        assert verify_password(users[name].password_hash, password)
    actions = [e["action"] for e in DbAuditLog(db_session).entries()]
    assert actions.count("USER_CREATED") == 4 and actions.count("FUND_CREATED") == 1


def test_dev_bootstrap_leaves_a_populated_database_alone(db_session, make_user):
    make_user("someone", "analyst")
    assert cli.dev_bootstrap(db_session) == {}
    db_session.commit()
    assert db_session.execute(select(Fund)).first() is None


def test_commands_are_offered():
    parser = cli.build_parser()
    for command in ("dev", "serve", "worker", "migrate"):
        assert parser.parse_args([command]).command == command
    args = parser.parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert (args.host, args.port) == ("0.0.0.0", 9000)
    args = parser.parse_args(["dev"])
    assert (args.host, args.port) == ("127.0.0.1", 8000)
