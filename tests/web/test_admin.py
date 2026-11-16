"""Administration: users, funds, the AI switch (engine change 4) and their audit entries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from reconpilot.ai import COMPATIBLE_ENV, KEY_ENV
from reconpilot_web import runner
from reconpilot_web.models import AuditEntry, Fund, User

from .conftest import FUND_CODE, FUND_START, TEST_PASSWORD, sign_in

NEW_PASSWORD = "Harbour-Lantern-9052"


@pytest.fixture(autouse=True)
def no_ai_environment(monkeypatch):
    """No provider is configured unless a test sets one, whatever the machine's environment holds."""
    for var in [*KEY_ENV.values(), *COMPATIBLE_ENV.values(), "RP_AI_PROVIDER", "RP_AI_MODEL"]:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def admin(make_user, users, make_client):
    """``admin1`` (an approver with the admin flag) signed in; the standard users exist too."""
    make_user("admin1", "approver", is_admin=True, display_name="Ada Admin")
    return make_client("admin1")


def entries(db_session, action: str) -> list[dict]:
    """The audit entries with this action, oldest first, each with its fund's code."""
    db_session.expire_all()
    codes = {f.id: f.code for f in db_session.execute(select(Fund)).scalars()}
    rows = db_session.execute(select(AuditEntry).where(AuditEntry.action == action).order_by(AuditEntry.seq))
    return [{"actor": e.actor, "role": e.role, "payload": e.payload, "fund": codes.get(e.fund_id)}
            for e in rows.scalars()]


def user_row(db_session, username: str) -> User:
    db_session.expire_all()
    return db_session.execute(select(User).where(User.username == username)).scalar_one()


# --------------------------------------------------------------------------- who may administer


ADMIN_ROUTES = [
    ("get", "/api/admin/users", None),
    ("post", "/api/admin/users", {"username": "x", "password": NEW_PASSWORD, "role": "viewer"}),
    ("patch", "/api/admin/users/viewer1", {"role": "analyst"}),
    ("post", "/api/admin/users/viewer1/password", {"password": NEW_PASSWORD}),
    ("post", "/api/admin/users/viewer1/unlock", None),
    ("get", "/api/admin/ai/providers", None),
    ("post", "/api/admin/funds", {"code": "NEW1", "name": "New", "start_date": str(FUND_START)}),
    ("get", f"/api/admin/funds/{FUND_CODE}", None),
    ("patch", f"/api/admin/funds/{FUND_CODE}", {"name": "Renamed"}),
    ("put", f"/api/admin/funds/{FUND_CODE}/ai", {"enabled": True, "acknowledged": True}),
]


@pytest.mark.parametrize("username", ["analyst1", "approver1", "viewer1"])
def test_only_administrators_reach_admin_routes(make_client, users, fund, username):
    client = make_client(username)
    for method, path, body in ADMIN_ROUTES:
        response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 403, (method, path, response.text)


def test_signed_out_is_refused(client, users, fund):
    for method, path, body in ADMIN_ROUTES:
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, **kwargs).status_code in (401, 403), (method, path)


# --------------------------------------------------------------------------- users


def test_list_users(admin):
    users = {u["username"]: u for u in admin.get("/api/admin/users").json()}
    assert sorted(users) == ["admin1", "analyst1", "approver1", "approver2", "viewer1"]
    assert users["admin1"]["is_admin"] and users["admin1"]["live_sessions"] == 1
    assert users["analyst1"] == {
        "username": "analyst1", "display_name": "Priya Shah", "role": "analyst", "is_admin": False,
        "is_active": True, "locked": False, "locked_until": None, "failed_logins": 0, "last_login_at": None,
        "created_at": users["analyst1"]["created_at"], "live_sessions": 0,
    }


def test_create_user_applies_the_password_policy_and_is_audited(admin, make_client, db_session):
    bad = admin.post("/api/admin/users", json={"username": "newbie", "password": "short", "role": "analyst"})
    assert bad.status_code == 422
    wrong_role = admin.post("/api/admin/users", json={"username": "newbie", "password": NEW_PASSWORD, "role": "boss"})
    assert wrong_role.status_code == 422
    made = admin.post("/api/admin/users", json={"username": "Newbie", "password": NEW_PASSWORD, "role": "analyst",
                                                "display_name": "Nell Newby"})
    assert made.status_code == 201, made.text
    assert made.json()["username"] == "newbie" and made.json()["display_name"] == "Nell Newby"
    taken = admin.post("/api/admin/users", json={"username": "newbie", "password": NEW_PASSWORD, "role": "viewer"})
    assert taken.status_code == 422 and "already exists" in taken.json()["detail"]
    (entry,) = entries(db_session, "USER_CREATED")[-1:]
    assert entry["actor"] == "admin1" and entry["payload"]["username"] == "newbie"
    make_client("newbie", NEW_PASSWORD)  # the new user can sign in


def test_role_change_revokes_sessions_and_is_audited(admin, make_client, db_session):
    analyst = make_client("analyst1")
    assert analyst.get("/api/auth/me").json()["role"] == "analyst"
    response = admin.patch("/api/admin/users/analyst1", json={"role": "approver"})
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "approver" and response.json()["live_sessions"] == 0
    assert analyst.get("/api/auth/me").status_code == 401  # the old session is gone at once
    (entry,) = entries(db_session, "USER_ROLE_CHANGED")
    assert entry["payload"] == {"username": "analyst1", "from": "analyst", "to": "approver", "sessions_revoked": 1}
    assert make_client("analyst1").get("/api/auth/me").json()["role"] == "approver"
    assert admin.patch("/api/admin/users/analyst1", json={"role": "chief"}).status_code == 422


def test_rename_and_admin_flag(admin, make_client, db_session):
    viewer = make_client("viewer1")
    response = admin.patch("/api/admin/users/viewer1", json={"display_name": "Victoria Moss", "is_admin": True})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Victoria Moss" and response.json()["is_admin"]
    assert viewer.get("/api/auth/me").status_code == 401
    assert entries(db_session, "USER_RENAMED")[0]["payload"] == {
        "username": "viewer1", "from": "Vic Moss", "to": "Victoria Moss"}
    assert entries(db_session, "USER_ADMIN_CHANGED")[0]["payload"]["is_admin"] is True


def test_deactivate_and_reactivate(admin, make_client, client, db_session):
    viewer = make_client("viewer1")
    response = admin.patch("/api/admin/users/viewer1", json={"is_active": False})
    assert response.status_code == 200 and response.json()["is_active"] is False
    assert viewer.get("/api/auth/me").status_code == 401
    refused = client.post("/api/auth/login", json={"username": "viewer1", "password": TEST_PASSWORD})
    assert refused.status_code == 401
    assert entries(db_session, "USER_DEACTIVATED")[0]["payload"] == {"username": "viewer1", "sessions_revoked": 1}
    assert admin.patch("/api/admin/users/viewer1", json={"is_active": True}).json()["is_active"] is True
    assert entries(db_session, "USER_REACTIVATED")[0]["payload"] == {"username": "viewer1"}
    make_client("viewer1")


def test_password_reset_revokes_sessions_and_clears_a_lockout(admin, make_client, client, db_session):
    analyst = make_client("analyst1")
    too_short = admin.post("/api/admin/users/analyst1/password", json={"password": "abc"})
    assert too_short.status_code == 422
    response = admin.post("/api/admin/users/analyst1/password", json={"password": NEW_PASSWORD})
    assert response.status_code == 200, response.text
    assert analyst.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "analyst1", "password": TEST_PASSWORD}).status_code == 401
    make_client("analyst1", NEW_PASSWORD)
    assert entries(db_session, "PASSWORD_RESET")[0]["payload"] == {"username": "analyst1", "sessions_revoked": 1}


def test_unlock_a_locked_account(admin, client, make_client, db_session):
    assert admin.post("/api/admin/users/viewer1/unlock").status_code == 409  # not locked
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "viewer1", "password": "Wrong-Password-000"})
    listed = {u["username"]: u for u in admin.get("/api/admin/users").json()}
    assert listed["viewer1"]["locked"] and listed["viewer1"]["locked_until"]
    assert client.post("/api/auth/login", json={"username": "viewer1", "password": TEST_PASSWORD}).status_code == 423
    response = admin.post("/api/admin/users/viewer1/unlock")
    assert response.status_code == 200 and response.json()["locked"] is False
    assert user_row(db_session, "viewer1").failed_logins == 0
    (entry,) = entries(db_session, "ACCOUNT_UNLOCKED")
    assert entry["actor"] == "admin1" and entry["payload"]["username"] == "viewer1"
    make_client("viewer1")


def test_an_administrator_cannot_change_their_own_account(admin):
    for method, path, body in [
        ("patch", "/api/admin/users/admin1", {"is_active": False}),
        ("patch", "/api/admin/users/admin1", {"is_admin": False}),
        ("patch", "/api/admin/users/ADMIN1", {"role": "viewer"}),
        ("post", "/api/admin/users/admin1/password", {"password": NEW_PASSWORD}),
    ]:
        response = getattr(admin, method)(path, json=body)
        assert response.status_code == 409, (path, body)
        assert "another administrator" in response.json()["detail"]
    assert admin.get("/api/auth/me").status_code == 200


def test_unknown_user_is_404(admin):
    assert admin.patch("/api/admin/users/nobody", json={"role": "viewer"}).status_code == 404
    assert admin.post("/api/admin/users/nobody/unlock").status_code == 404


def test_audit_chain_still_verifies(admin, db_session):
    admin.patch("/api/admin/users/viewer1", json={"role": "analyst"})
    admin.post("/api/admin/users/analyst1/password", json={"password": NEW_PASSWORD})
    assert admin.post("/api/audit/verify").json()["chain_ok"] is True


# --------------------------------------------------------------------------- funds


def test_create_fund(admin, db_session):
    body = {"code": "inc2", "name": "Income Fund", "start_date": "2026-11-09",
            "non_business_dates": ["2026-11-26"], "settings": {"materiality_bp": 2.5}}
    response = admin.post("/api/admin/funds", json=body)
    assert response.status_code == 201, response.text
    fund = response.json()
    assert fund["code"] == "INC2" and fund["settings"]["materiality_bp"] == 2.5
    assert fund["non_business_dates"] == ["2026-11-26"]
    assert fund["ai"] == {"enabled": False, "provider": None, "effective_provider": None, "model": None}
    created = entries(db_session, "FUND_CREATED")[-1]
    assert created["actor"] == "admin1" and created["fund"] == "INC2"
    assert admin.post("/api/admin/funds", json=body).status_code == 422  # taken
    weekend = {**body, "code": "W1", "start_date": "2026-11-14"}
    assert admin.post("/api/admin/funds", json=weekend).status_code == 422


def test_create_fund_cannot_switch_ai_on(admin):
    body = {"code": "AI1", "name": "AI Fund", "start_date": "2026-11-09", "settings": {"ai_enabled": True}}
    response = admin.post("/api/admin/funds", json=body)
    assert response.status_code == 422 and "AI switch" in response.json()["detail"]


def test_change_settings_records_each_change(admin, fund, db_session):
    response = admin.patch(f"/api/admin/funds/{FUND_CODE}", json={
        "name": "Global Equity Fund II",
        "settings": {"materiality_bp": 0.5, "sla_days_other": 3,
                     "check_settings": {"cash_tolerance": 5.0, "price_move_limits": {"EQUITY": 0.15, "BOND": 0.03}}},
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Global Equity Fund II"
    assert body["settings"]["materiality_bp"] == 0.5 and body["settings"]["sla_days_other"] == 3
    assert body["checks_in_force"]["cash_tolerance"] == 5.0
    assert body["checks_in_force"]["price_move_limits"] == {"EQUITY": 0.15, "BOND": 0.03}
    (entry,) = entries(db_session, "FUND_SETTINGS_CHANGED")
    changes = entry["payload"]["changes"]
    assert changes["name"] == {"from": "Global Equity Fund", "to": "Global Equity Fund II"}
    assert changes["materiality_bp"] == {"from": 1.0, "to": 0.5}
    assert changes["sla_days_other"] == {"from": 5, "to": 3}
    assert set(changes) == {"name", "materiality_bp", "sla_days_other", "check_settings"}
    assert entry["fund"] == FUND_CODE

    # Sending the same values again changes nothing and writes nothing.
    admin.patch(f"/api/admin/funds/{FUND_CODE}", json={"settings": {"materiality_bp": 0.5}})
    assert len(entries(db_session, "FUND_SETTINGS_CHANGED")) == 1


@pytest.mark.parametrize("changes, words", [
    ({"materiality_bp": -1}, "materiality_bp"),
    ({"escalate_after_days": 1.5}, "escalate_after_days"),
    ({"ai_enabled": True}, "AI switch"),
    ({"surprise": 1}, "Unknown fund settings"),
    ({"check_settings": {"nonsense": 1}}, "Unknown check settings"),
    ({"check_settings": {"cash_tolerance": -2}}, "cash_tolerance"),
    ({"check_settings": {"max_price_age_days": 0.5}}, "max_price_age_days"),
    ({"check_settings": {"price_move_limits": {"EQUITY": 2}}}, "EQUITY"),
])
def test_bad_settings_are_refused_and_nothing_changes(admin, fund, db_session, changes, words):
    response = admin.patch(f"/api/admin/funds/{FUND_CODE}", json={"settings": changes, "name": "Changed"})
    assert response.status_code == 422 and words in response.json()["detail"]
    db_session.expire_all()
    stored = db_session.execute(select(Fund).where(Fund.code == FUND_CODE)).scalar_one()
    assert stored.name == "Global Equity Fund"
    assert not entries(db_session, "FUND_SETTINGS_CHANGED")


def test_calendar_changes_only_after_the_latest_loaded_day(admin, make_client, fund, day_files, db_session):
    from .test_upload import upload

    url = f"/api/admin/funds/{FUND_CODE}"
    ok = admin.patch(url, json={"non_business_dates": ["2026-11-26", "2026-12-25"]})
    assert ok.status_code == 200 and ok.json()["non_business_dates"] == ["2026-11-26", "2026-12-25"]
    (entry,) = entries(db_session, "FUND_CALENDAR_CHANGED")
    assert entry["payload"] == {"code": FUND_CODE, "added": ["2026-11-26", "2026-12-25"], "removed": []}

    assert admin.patch(url, json={"non_business_dates": [str(FUND_START)]}).status_code == 409  # the start date
    assert admin.patch(url, json={"non_business_dates": ["2026-11-28"]}).status_code == 422  # a Saturday

    assert upload(make_client("analyst1"), day_files[0]).status_code == 200  # 9 November is loaded
    early = admin.patch(url, json={"non_business_dates": ["2026-11-09", "2026-11-26", "2026-12-25"]})
    assert early.status_code == 409 and "latest loaded day" in early.json()["detail"]
    removed = admin.patch(url, json={"non_business_dates": ["2026-11-26"]})
    assert removed.status_code == 200
    assert entries(db_session, "FUND_CALENDAR_CHANGED")[-1]["payload"]["removed"] == ["2026-12-25"]


def test_unknown_fund_is_404(admin):
    assert admin.get("/api/admin/funds/NOPE").status_code == 404
    assert admin.patch("/api/admin/funds/NOPE", json={"name": "x"}).status_code == 404


# --------------------------------------------------------------------------- AI switch


def test_providers_show_what_the_server_has_and_never_a_key(admin, monkeypatch):
    body = admin.get("/api/admin/ai/providers").json()
    assert body["default"] is None
    assert [p["provider"] for p in body["providers"]] == ["anthropic", "openai", "google", "openai_compatible"]
    assert not any(p["configured"] for p in body["providers"])

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.bank.internal/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "private-secret-value")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "house-7b")
    response = admin.get("/api/admin/ai/providers")
    assert "secret-value" not in response.text
    body = response.json()
    providers = {p["provider"]: p for p in body["providers"]}
    assert body["default"] == "openai"
    assert providers["openai"]["configured"] and providers["openai"]["model"] == "gpt-6-luna"
    assert providers["openai"]["private"] is False
    assert providers["openai_compatible"] == {
        "provider": "openai_compatible", "label": "Private endpoint (OpenAI-compatible)", "configured": True,
        "model": "house-7b", "private": True, "endpoint": "llm.bank.internal", "problem": None,
    }
    assert "ANTHROPIC_API_KEY" in providers["anthropic"]["problem"]


def test_switching_ai_on_needs_a_configured_provider_and_an_acknowledgement(admin, fund, db_session, monkeypatch):
    url = f"/api/admin/funds/{FUND_CODE}/ai"
    nothing = admin.put(url, json={"enabled": True, "acknowledged": True})
    assert nothing.status_code == 409 and "no AI provider" in nothing.json()["detail"]
    unset = admin.put(url, json={"enabled": True, "provider": "google", "acknowledged": True})
    assert unset.status_code == 409 and "GOOGLE_API_KEY" in unset.json()["detail"]
    assert admin.put(url, json={"enabled": True, "provider": "skynet", "acknowledged": True}).status_code == 422

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    unconfirmed = admin.put(url, json={"enabled": True, "provider": "openai"})
    assert unconfirmed.status_code == 422 and "outside the firm" in unconfirmed.json()["detail"]
    assert not entries(db_session, "AI_SWITCHED_ON")

    on = admin.put(url, json={"enabled": True, "provider": "openai", "acknowledged": True})
    assert on.status_code == 200, on.text
    assert on.json()["settings"]["ai_enabled"] is True
    assert on.json()["ai"] == {"enabled": True, "provider": "openai", "effective_provider": "openai",
                               "model": "gpt-6-luna"}
    (entry,) = entries(db_session, "AI_SWITCHED_ON")
    assert entry["fund"] == FUND_CODE and entry["actor"] == "admin1"
    assert entry["payload"] == {"provider": "openai", "model": "gpt-6-luna", "chosen": "fund",
                                "evidence_sent_to": "OpenAI", "leaves_firm": True}
    again = admin.put(url, json={"enabled": True, "provider": "openai", "acknowledged": True})
    assert again.status_code == 409

    off = admin.put(url, json={"enabled": False})
    assert off.status_code == 200 and off.json()["settings"]["ai_enabled"] is False
    (entry,) = entries(db_session, "AI_SWITCHED_OFF")
    assert entry["payload"] == {"provider": "openai", "model": "gpt-6-luna"}
    assert admin.put(url, json={"enabled": False}).status_code == 409
    # The fund screen everyone sees agrees.
    assert admin.get(f"/api/funds/{FUND_CODE}").json()["settings"]["ai_enabled"] is False


def test_switching_to_the_private_endpoint(admin, fund, db_session, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.bank.internal/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "house-7b")
    url = f"/api/admin/funds/{FUND_CODE}/ai"
    unconfirmed = admin.put(url, json={"enabled": True, "provider": "openai_compatible"})
    assert unconfirmed.status_code == 422 and "llm.bank.internal" in unconfirmed.json()["detail"]
    assert admin.put(url, json={"enabled": True, "acknowledged": True}).status_code == 200  # server default
    assert entries(db_session, "AI_SWITCHED_ON")[0]["payload"]["chosen"] == "server default"
    moved = admin.put(url, json={"enabled": True, "provider": "openai_compatible", "acknowledged": True})
    assert moved.status_code == 200
    payload = entries(db_session, "AI_SWITCHED_ON")[1]["payload"]
    assert payload == {"provider": "openai_compatible", "model": "house-7b", "chosen": "fund",
                       "evidence_sent_to": "llm.bank.internal", "leaves_firm": False,
                       "previous_provider": "openai", "previous_model": "gpt-6-luna"}


def test_a_bad_private_endpoint_is_reported(admin, fund, monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "ftp://llm.bank.internal")
    providers = {p["provider"]: p for p in admin.get("/api/admin/ai/providers").json()["providers"]}
    assert not providers["openai_compatible"]["configured"]
    assert "https://" in providers["openai_compatible"]["problem"]
    response = admin.put(f"/api/admin/funds/{FUND_CODE}/ai",
                         json={"enabled": True, "provider": "openai_compatible", "acknowledged": True})
    assert response.status_code == 409


def test_the_runner_uses_the_funds_provider(monkeypatch):
    """``runner.ai_client`` asks for the fund's provider; ``RP_AI_MODEL`` names the default provider's model only."""
    asked = []
    monkeypatch.setattr(runner, "make_client", lambda *a, **k: asked.append(a) or None)
    monkeypatch.setenv("RP_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("RP_AI_MODEL", "claude-special")
    runner.ai_client("openai_compatible")
    runner.ai_client(None)
    runner.ai_client("anthropic")
    assert [a[:2] for a in asked] == [("openai_compatible", None), ("anthropic", "claude-special"),
                                      ("anthropic", "claude-special")]


def test_a_run_uses_the_provider_the_administrator_chose(admin, make_client, fund, day_files, db_session,
                                                         monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from .test_release import run_day
    from .test_runner import FakeClient

    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.bank.internal/v1")
    assert admin.put(f"/api/admin/funds/{FUND_CODE}/ai", json={
        "enabled": True, "provider": "openai_compatible", "acknowledged": True}).status_code == 200
    asked, client = [], FakeClient()
    monkeypatch.setattr(runner, "make_client", lambda *a, **k: asked.append(a[0]) or client)
    run_day(make_client("analyst1"), sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
            day_files[0])
    assert asked == ["openai_compatible"] and client.calls > 0


def test_demo_users_are_not_listed(admin, db_session):
    from reconpilot_web.auth import create_user

    demo_fund = Fund(code="DEMO1", name="Demo", start_date=FUND_START, is_demo=True,
                     demo_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db_session.add(demo_fund)
    db_session.flush()
    visitor = create_user(db_session, "demo-analyst-1", NEW_PASSWORD, "analyst")
    visitor.demo_fund_id = demo_fund.id
    db_session.commit()
    assert "demo-analyst-1" not in [u["username"] for u in admin.get("/api/admin/users").json()]
    assert admin.patch("/api/admin/users/demo-analyst-1", json={"role": "viewer"}).status_code == 404
    assert admin.get("/api/admin/funds/DEMO1").status_code == 404


def test_another_administrator_can_change_one(make_client, make_user, users):
    """A second administrator can change the first (so there is always someone to do it)."""
    make_user("admin1", "approver", is_admin=True)
    make_user("admin2", "viewer", is_admin=True)
    second = make_client("admin2")
    assert second.patch("/api/admin/users/admin1", json={"is_admin": False}).status_code == 200
    first = sign_in(make_client(), "admin1")
    assert first.get("/api/admin/users").status_code == 403
