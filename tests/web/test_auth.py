"""Accounts, sessions, CSRF, lockout, roles and security headers."""

from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from reconpilot_web import cli
from reconpilot_web.auditlog import DbAuditLog, verify_chain
from reconpilot_web.auth import current_user, require_admin, require_roles
from reconpilot_web.models import User, UserSession
from reconpilot_web.security import (
    check_password_policy,
    hash_password,
    new_token,
    token_digest,
    verify_password,
)

from .conftest import TEST_PASSWORD, make_settings, sign_in


def _actions(db_session) -> list[str]:
    return [e["action"] for e in DbAuditLog(db_session).entries()]


# --------------------------------------------------------------------------- security primitives


def test_password_hashing_is_argon2id():
    hashed = hash_password(TEST_PASSWORD)
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, TEST_PASSWORD)
    assert not verify_password(hashed, TEST_PASSWORD + "x")
    assert not verify_password("not a hash", TEST_PASSWORD)


def test_tokens_are_random_and_digested():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 43
    assert token_digest(a) == token_digest(a) and len(token_digest(a)) == 64 and token_digest(a) != a


def test_password_policy():
    assert check_password_policy("short")
    assert check_password_policy("password1234")
    assert check_password_policy("qwertyuiop123")
    assert check_password_policy("aaaaaaaaaaaa")
    assert check_password_policy("Password12345")
    assert check_password_policy(secrets.token_urlsafe(12)[:16]) == []
    assert check_password_policy("Ledger-Walrus-4817") == []


# --------------------------------------------------------------------------- sign-in and sessions


def test_login_sets_cookies_and_me_works(client, users, db_session):
    response = client.post("/api/auth/login", json={"username": "analyst1", "password": TEST_PASSWORD})
    assert response.status_code == 200
    assert response.json() == {
        "user": {"username": "analyst1", "display_name": "Priya Shah", "role": "analyst", "is_admin": False}
    }
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("rp_session="))
    csrf_cookie = next(c for c in cookies if c.startswith("rp_csrf="))
    assert "HttpOnly" in session_cookie and "samesite=lax" in session_cookie.lower()
    assert "HttpOnly" not in csrf_cookie
    assert "Secure" not in session_cookie  # RP_COOKIE_SECURE is off in tests

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"username": "analyst1", "display_name": "Priya Shah", "role": "analyst", "is_admin": False}

    # Only the token's digest is stored.
    token = client.cookies["rp_session"]
    stored = db_session.execute(select(UserSession)).scalar_one()
    assert stored.token_hash == token_digest(token) and stored.token_hash != token
    assert stored.expires_at - stored.created_at == timedelta(hours=12)
    assert _actions(db_session)[-1] == "SIGN_IN"


def test_secure_cookie_when_configured(make_client, users, settings, app):
    app.state.settings = cli.load_settings(
        {"RP_DATABASE_URL": settings.database_url, "RP_COOKIE_SECURE": "1", "RP_DATA_DIR": str(settings.data_dir)}
    )
    response = make_client().post("/api/auth/login", json={"username": "analyst1", "password": TEST_PASSWORD})
    assert all("Secure" in c for c in response.headers.get_list("set-cookie"))


def test_wrong_password_401_and_audited(client, users, db_session):
    response = client.post("/api/auth/login", json={"username": "analyst1", "password": "wrong-password-123"})
    assert response.status_code == 401
    assert "rp_session" not in client.cookies
    unknown = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password-123"})
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == response.json()["detail"]

    entries = [e for e in DbAuditLog(db_session).entries() if e["action"] == "SIGN_IN_FAILED"]
    assert [(e["actor"], e["payload"]["reason"]) for e in entries] == [
        ("analyst1", "wrong password"),
        ("nobody", "unknown user"),
    ]
    assert all(set(e["payload"]) <= {"reason", "failed_logins", "ip"} for e in entries)  # never the password
    user = db_session.execute(select(User).where(User.username == "analyst1")).scalar_one()
    assert user.failed_logins == 1
    assert client.get("/api/auth/me").status_code == 401


def test_lockout_after_five_failures(client, users, db_session):
    codes = [
        client.post("/api/auth/login", json={"username": "analyst1", "password": f"wrong-{i}-password"}).status_code
        for i in range(5)
    ]
    assert codes == [401, 401, 401, 401, 423]
    sixth = client.post("/api/auth/login", json={"username": "analyst1", "password": TEST_PASSWORD})
    assert sixth.status_code == 423
    assert "rp_session" not in client.cookies
    actions = _actions(db_session)
    assert actions.count("ACCOUNT_LOCKED") == 1
    assert actions.count("SIGN_IN_FAILED") == 6

    # After 15 minutes the account opens again and the counter starts afresh.
    db_session.execute(update(User).where(User.username == "analyst1").values(
        locked_until=User.locked_until - timedelta(minutes=15, seconds=1)))
    db_session.commit()
    sign_in(client, "analyst1")
    user = db_session.execute(select(User).where(User.username == "analyst1")).scalar_one()
    db_session.refresh(user)
    assert user.failed_logins == 0 and user.locked_until is None


def test_success_resets_failure_count(client, users, db_session):
    for _ in range(4):
        client.post("/api/auth/login", json={"username": "analyst1", "password": "wrong-password-123"})
    sign_in(client, "analyst1")
    client.post("/api/auth/logout")
    for _ in range(4):
        assert client.post("/api/auth/login", json={"username": "analyst1", "password": "wrong-password-123"}).status_code == 401


def test_inactive_user_cannot_sign_in_or_use_session(make_client, users, db_session):
    signed_in = make_client("analyst1")
    db_session.execute(update(User).where(User.username == "analyst1").values(is_active=False))
    db_session.commit()
    assert signed_in.get("/api/auth/me").status_code == 401
    response = make_client().post("/api/auth/login", json={"username": "analyst1", "password": TEST_PASSWORD})
    assert response.status_code == 401


def test_logout_then_cookie_replay_401(make_client, users, db_session):
    client = make_client("analyst1")
    token = client.cookies["rp_session"]
    csrf = client.cookies["rp_csrf"]
    assert client.post("/api/auth/logout").status_code == 204
    assert "rp_session" not in client.cookies
    assert _actions(db_session)[-1] == "SIGN_OUT"

    replay = make_client()
    replay.cookies.set("rp_session", token)
    replay.cookies.set("rp_csrf", csrf)
    replay.headers["X-CSRF-Token"] = csrf
    assert replay.get("/api/auth/me").status_code == 401
    assert replay.post("/api/auth/logout").status_code == 401


def test_post_without_csrf_403(make_client, users):
    client = make_client("analyst1")
    del client.headers["X-CSRF-Token"]
    assert client.post("/api/auth/logout").status_code == 403
    client.headers["X-CSRF-Token"] = "forged"
    assert client.post("/api/auth/logout").status_code == 403
    # The cookie and header agree but belong to no session of this user: refused too.
    forged = new_token()
    client.cookies.set("rp_csrf", forged)
    client.headers["X-CSRF-Token"] = forged
    assert client.post("/api/auth/logout").status_code == 403
    assert client.get("/api/auth/me").status_code == 200  # still signed in


def test_idle_timeout_expires_session(make_client, users, db_session):
    client = make_client("analyst1")
    assert client.get("/api/auth/me").status_code == 200
    db_session.execute(update(UserSession).values(last_seen_at=UserSession.last_seen_at - timedelta(minutes=31)))
    db_session.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_absolute_timeout_expires_active_session(make_client, users, db_session):
    client = make_client("analyst1")
    db_session.execute(update(UserSession).values(
        created_at=UserSession.created_at - timedelta(hours=12, seconds=1),
        expires_at=UserSession.expires_at - timedelta(hours=12, seconds=1),
    ))
    db_session.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_requests_keep_session_alive(make_client, users, db_session):
    client = make_client("analyst1")
    db_session.execute(update(UserSession).values(last_seen_at=UserSession.last_seen_at - timedelta(minutes=29)))
    db_session.commit()
    assert client.get("/api/auth/me").status_code == 200
    db_session.execute(update(UserSession).values(last_seen_at=UserSession.last_seen_at - timedelta(minutes=29)))
    db_session.commit()
    assert client.get("/api/auth/me").status_code == 200


# --------------------------------------------------------------------------- roles


@pytest.fixture
def role_routes(app):
    @app.post("/api/test/analyst-or-approver")
    def act(user: User = Depends(require_roles("analyst", "approver"))):
        return {"ok": user.username}

    @app.get("/api/test/admin")
    def admin(user: User = Depends(require_admin)):
        return {"ok": user.username}

    @app.get("/api/test/anyone")
    def anyone(user: User = Depends(current_user)):
        return {"ok": user.username}

    return app


def test_roles_enforced_on_the_server(role_routes, make_client, users, make_user):
    make_user("admin1", "viewer", is_admin=True)
    expected = {"analyst1": (200, 403), "approver1": (200, 403), "viewer1": (403, 403), "admin1": (403, 200)}
    for username, (act_code, admin_code) in expected.items():
        c = make_client(username)
        assert c.post("/api/test/analyst-or-approver").status_code == act_code, username
        assert c.get("/api/test/admin").status_code == admin_code, username
        assert c.get("/api/test/anyone").status_code == 200
    anonymous = make_client()
    assert anonymous.get("/api/test/anyone").status_code == 401
    assert anonymous.get("/api/test/admin").status_code == 401


def test_require_roles_rejects_unknown_role():
    with pytest.raises(ValueError):
        require_roles("superuser")


# --------------------------------------------------------------------------- headers, users, audit


def test_security_headers_present(client, users):
    for response in (client.get("/api/auth/me"), client.post("/api/auth/login", json={"username": "x", "password": "y"})):
        assert response.headers["Content-Security-Policy"] == "default-src 'self'; frame-ancestors 'none'"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "same-origin"


def test_login_accepts_json_only(client, users):
    response = client.post("/api/auth/login", data={"username": "analyst1", "password": TEST_PASSWORD})
    assert response.status_code == 422
    assert "rp_session" not in client.cookies


def test_create_user_validates_and_audits(make_user, db_session):
    make_user("analyst1", "analyst")
    with pytest.raises(ValueError, match="already exists"):
        make_user("analyst1", "analyst")
    with pytest.raises(ValueError, match="too common"):
        make_user("analyst2", "analyst", password="password1234")
    with pytest.raises(ValueError, match="Role"):
        make_user("analyst3", "trader")
    entries = [e for e in DbAuditLog(db_session).entries() if e["action"] == "USER_CREATED"]
    assert [e["payload"] for e in entries] == [{"username": "analyst1", "role": "analyst", "is_admin": False}]


def test_cli_create_user(monkeypatch, capsys, clean_db, pg_uri, pg_dir, db_session):
    monkeypatch.setenv("RP_DATABASE_URL", pg_uri)
    monkeypatch.delenv("RP_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("RP_DATA_DIR", str(pg_dir))
    monkeypatch.setenv("RP_MODE", "real")
    monkeypatch.setenv("RP_NEW_PASSWORD", TEST_PASSWORD)
    args = ["create-user", "--username", "ann", "--role", "approver", "--admin", "--display-name", "Ann Lee"]
    assert cli.main(args) == 0
    assert "Created approver ann (admin)" in capsys.readouterr().out
    user = db_session.execute(select(User).where(User.username == "ann")).scalar_one()
    assert (user.role, user.is_admin, user.display_name) == ("approver", True, "Ann Lee")
    assert verify_password(user.password_hash, TEST_PASSWORD)

    monkeypatch.setenv("RP_NEW_PASSWORD", "short")
    assert cli.main(["create-user", "--username", "bob", "--role", "viewer"]) == 1
    assert "at least 12 characters" in capsys.readouterr().err


def test_auth_events_keep_the_chain(make_client, users, db_session):
    c = make_client("analyst1")
    c.post("/api/auth/logout")
    make_client().post("/api/auth/login", json={"username": "approver1", "password": "wrong-password-1"})
    assert verify_chain(db_session) == (True, None)
    assert _actions(db_session) == ["USER_CREATED"] * 4 + ["SIGN_IN", "SIGN_OUT", "SIGN_IN_FAILED"]


def test_app_works_as_the_restricted_database_role(app_db_uri, pg_dir, users, db_session):
    from reconpilot_web.app import create_app

    application = create_app(make_settings(app_db_uri, pg_dir))
    try:
        with TestClient(application) as c:
            sign_in(c, "analyst1")
            assert c.get("/api/auth/me").status_code == 200
            assert c.post("/api/auth/logout").status_code == 204
            for i in range(5):
                c.post("/api/auth/login", json={"username": "viewer1", "password": f"wrong-{i}-password"})
    finally:
        application.state.engine.dispose()
    assert _actions(db_session)[-2:] == ["SIGN_IN_FAILED", "ACCOUNT_LOCKED"]
    assert verify_chain(db_session) == (True, None)


def test_app_refuses_database_of_other_mode(clean_db, pg_uri, pg_dir):
    from reconpilot_web.app import create_app

    with pytest.raises(RuntimeError, match="this instance runs in demo mode"):
        create_app(make_settings(pg_uri, pg_dir, mode="demo"))


# --------------------------------------------------------------------------- hardening


def test_security_headers_on_unhandled_error(app):
    @app.get("/api/test/boom")
    def boom() -> dict:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/api/test/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    assert response.headers["Content-Security-Policy"] == "default-src 'self'; frame-ancestors 'none'"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["Cache-Control"] == "no-store"


def test_nul_in_username_is_a_failed_sign_in(client, users, db_session):
    response = client.post("/api/auth/login", json={"username": "analyst1\x00", "password": TEST_PASSWORD})
    assert response.status_code == 401
    failed = [e for e in DbAuditLog(db_session).entries() if e["action"] == "SIGN_IN_FAILED"]
    assert failed[-1]["actor"] == "analyst1�"
    assert verify_chain(db_session) == (True, None)
    with pytest.raises(ValueError, match="control characters"):
        from reconpilot_web.auth import create_user

        create_user(db_session, "bad\x00name", TEST_PASSWORD, "analyst")


def test_usernames_are_case_insensitive(make_user, make_client, db_session):
    make_user("Analyst1", "analyst")
    with pytest.raises(ValueError, match="already exists"):
        make_user("ANALYST1", "analyst")
    assert db_session.execute(select(User.username)).scalars().all() == ["analyst1"]
    for typed in ("analyst1", "Analyst1", " ANALYST1 "):
        c = make_client()
        response = c.post("/api/auth/login", json={"username": typed, "password": TEST_PASSWORD})
        assert response.status_code == 200, typed
        assert response.json()["user"]["username"] == "analyst1"


def test_signing_in_again_revokes_the_previous_session(client, users, db_session):
    sign_in(client, "analyst1")
    first = client.cookies["rp_session"]
    sign_in(client, "analyst1")
    assert client.cookies["rp_session"] != first
    rows = db_session.execute(select(UserSession).order_by(UserSession.id)).scalars().all()
    assert len(rows) == 2
    assert rows[0].revoked_at is not None and rows[1].revoked_at is None
    with TestClient(client.app, cookies={"rp_session": first}) as replay:
        assert replay.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200
