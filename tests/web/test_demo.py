"""Demo mode (spec section 11): visitor funds, one-click users, isolation, expiry, limits and the mode guard.

The tests share the session's embedded PostgreSQL. ``demo_db`` turns its instance mode to
``demo`` for one test and back to ``real`` afterwards, so the demo instance runs against
a demo database exactly as it would in production, and every other test still sees a
real one.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from reconpilot_web import aicache, cli, demo, jobs
from reconpilot_web.app import create_app
from reconpilot_web.auditlog import verify_chain
from reconpilot_web.models import AuditEntry, BusinessDay, CaseRow, Decision, Fund, Job, User, UserSession

from .conftest import make_settings

WEEK = [str(d.as_of) for d in demo.demo_days()[: demo.DEMO_WEEK]]
FRIDAY = WEEK[-1]


@pytest.fixture
def demo_db(clean_db, db_engine):
    """The test database as a demo database for one test."""
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE instance_settings SET mode = 'demo' WHERE id = 1"))
    yield clean_db
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE instance_settings SET mode = 'real' WHERE id = 1"))


@pytest.fixture
def demo_settings(pg_uri, pg_dir, demo_db):
    return make_settings(pg_uri, pg_dir, mode="demo")


@pytest.fixture
def demo_app(demo_settings):
    application = create_app(demo_settings)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def visitors(demo_app):
    """``visitors()`` -> a new browser (``TestClient``) on the demo instance, not yet started."""
    clients: list[TestClient] = []

    def _make() -> TestClient:
        c = TestClient(demo_app)
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.close()


def start(client: TestClient) -> dict:
    """Press "Try the demo" in ``client``; returns the response body. Asserts success."""
    response = client.post("/api/demo", json={})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = client.cookies["rp_csrf"]
    return response.json()


def switch(client: TestClient, name: str) -> dict:
    """Become the demo user whose username starts with ``name`` (priya, ann, tom, vic)."""
    me = client.get("/api/auth/me").json()
    username = next(u["username"] for u in me["demo"]["users"] if u["username"].startswith(name + "."))
    response = client.post("/api/demo/switch", json={"username": username})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = client.cookies["rp_csrf"]
    return response.json()["user"]


def factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


# --------------------------------------------------------------------------- the visitor's fund


def test_try_the_demo_builds_a_worked_week(visitors, db_engine):
    client = visitors()
    body = start(client)
    code = body["fund"]
    assert code.startswith("DEMO-")
    assert body["user"]["role"] == "analyst" and body["user"]["display_name"] == "Priya Shah"
    team = body["user"]["demo"]["users"]
    assert [(u["display_name"], u["role"]) for u in team] == [
        ("Priya Shah", "analyst"), ("Ann Lee", "approver"), ("Tom Reed", "approver"), ("Vic Moss", "viewer")]

    assert [f["code"] for f in client.get("/api/funds").json()] == [code]
    days = client.get(f"/api/funds/{code}/days").json()
    assert days["latest_day"] == FRIDAY and days["next_day"] is None
    statuses = {d["as_of"]: (d["status"], d["signed_off_by"]) for d in days["days"]}
    assert statuses == {**{d: ("signed_off", f"ann.{code[5:].lower()}") for d in WEEK[:-1]}, FRIDAY: ("ready", None)}

    # The last day waits for the visitor: its cases are open and pending, and it is not releasable.
    queue = client.get(f"/api/funds/{code}/days/{FRIDAY}/cases").json()
    assert queue and any(c["status"] == "PENDING" for c in queue)
    release = client.get(f"/api/funds/{code}/days/{FRIDAY}/release").json()
    assert release["ready"] is False

    with factory(db_engine)() as session:
        fund = session.execute(select(Fund).where(Fund.code == code)).scalar_one()
        assert fund.is_demo and fund.settings["ai_enabled"] is True
        assert fund.demo_expires_at > datetime.now(timezone.utc) + timedelta(hours=23)
        # The week was worked through the real decision code, by the analyst and the second approver.
        deciders = set(session.execute(
            select(User.username).join(Decision, Decision.user_id == User.id).where(Decision.fund_id == fund.id)
        ).scalars())
        assert deciders and {d.split(".")[0] for d in deciders} <= {"priya", "tom"}
        actions = list(session.execute(
            select(AuditEntry.action).where(AuditEntry.fund_id == fund.id).order_by(AuditEntry.seq)).scalars())
        assert actions.count("DAY_SIGNED_OFF") == 4 and actions.count("RUN_FINISHED") == 5
        assert "DEMO_FUND_CREATED" in actions and "AI_UNAVAILABLE" not in actions
        assert verify_chain(session) == (True, None)
        assert session.execute(select(func.count(Job.id)).where(Job.status == "done")).scalar_one() == 5


def test_the_ai_never_calls_a_provider_in_the_demo(visitors, db_engine, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

    def no_network(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("the demo called an AI provider")

    monkeypatch.setattr("reconpilot.ai._post_json", no_network)
    code = start(visitors())["fund"]
    with factory(db_engine)() as session:
        fund_id = session.execute(select(Fund.id).where(Fund.code == code)).scalar_one()
        calls = list(session.execute(
            select(AuditEntry.payload).where(AuditEntry.fund_id == fund_id, AuditEntry.action == "AI_CALL")
        ).scalars())
    meta = demo_cache_meta()
    assert calls
    for call in calls:
        assert call["provider"] == meta["provider"] and call["model"] == meta["model"]
        assert call["cached"] or call["fallback_reason"] == aicache.CACHE_MISS


def demo_cache_meta() -> dict:
    data = aicache.read_demo_cache()
    assert data is not None, "src/reconpilot_web/demo_ai_cache.json is missing"
    return data


# --------------------------------------------------------------------------- isolation


def test_nothing_is_shared_between_visitors(visitors, demo_app):
    alice, bob = visitors(), visitors()
    a_code, b_code = start(alice)["fund"], start(bob)["fund"]
    assert a_code != b_code
    b_case = bob.get(f"/api/funds/{b_code}/days/{FRIDAY}/cases").json()[0]
    b_job = bob.get(f"/api/funds/{b_code}/days/{FRIDAY}").json()["job"]["id"]
    b_seq = bob.get("/api/audit", params={"limit": 1}).json()["entries"][0]["seq"]
    b_ann = next(u["username"] for u in bob.get("/api/auth/me").json()["demo"]["users"] if u["role"] == "approver")

    # Alice sees her own fund only ...
    assert [f["code"] for f in alice.get("/api/funds").json()] == [a_code]
    # ... and every route about Bob's fund answers as if it did not exist.
    for path in (
        f"/api/funds/{b_code}",
        f"/api/funds/{b_code}/days",
        f"/api/funds/{b_code}/days/{FRIDAY}",
        f"/api/funds/{b_code}/days/{FRIDAY}/cases",
        f"/api/funds/{b_code}/days/{FRIDAY}/overview",
        f"/api/funds/{b_code}/days/{FRIDAY}/release",
        f"/api/funds/{b_code}/days/{FRIDAY}/audit",
        f"/api/funds/{b_code}/days/{FRIDAY}/mi",
        f"/api/funds/{b_code}/days/{FRIDAY}/exports/mi.csv",
        f"/api/funds/{b_code}/cases/{b_case['case_id']}",
        f"/api/jobs/{b_job}",
        f"/api/audit/entries/{b_seq}",
        f"/api/audit?fund={b_code}",
    ):
        assert alice.get(path).status_code == 404, path
    decision = alice.post(f"/api/funds/{b_code}/cases/{b_case['case_id']}/decision",
                          json={"decision": "approve", "version": b_case["version"]})
    assert decision.status_code == 404
    assert alice.put("/api/auth/me/preferences", json={"fund": b_code}).status_code == 404
    assert alice.post("/api/demo/switch", json={"username": b_ann}).status_code == 404

    # Alice's audit log, its facets and its export hold her fund's entries alone.
    entries = alice.get("/api/audit", params={"limit": 200}).json()["entries"]
    assert entries and {e["fund"] for e in entries} == {a_code}
    actors = set(alice.get("/api/audit/facets").json()["actors"])
    assert not any(a.endswith("." + b_code[5:].lower()) for a in actors)
    export = alice.get("/api/audit/export.csv").text
    assert b_code not in export and a_code in export

    # Bob's fund is untouched by any of it.
    assert bob.get(f"/api/funds/{b_code}/days/{FRIDAY}/cases").json()[0]["version"] == b_case["version"]


def test_role_switcher_moves_between_the_funds_own_users(visitors):
    client = visitors()
    code = start(client)["fund"]
    ann = switch(client, "ann")
    assert ann["role"] == "approver" and ann["display_name"] == "Ann Lee"
    assert client.get("/api/auth/me").json()["username"] == ann["username"]
    viewer = switch(client, "vic")
    assert viewer["role"] == "viewer"
    case = client.get(f"/api/funds/{code}/days/{FRIDAY}/cases").json()[0]
    response = client.post(f"/api/funds/{code}/cases/{case['case_id']}/decision",
                           json={"decision": "approve", "version": case["version"]})
    assert response.status_code == 403  # a viewer still cannot act
    assert client.post("/api/demo/switch", json={"username": "nobody.zzzzzz"}).status_code == 404


def test_a_visitor_returns_to_their_fund_after_their_session_ends(visitors, demo_app):
    client = visitors()
    code = start(client)["fund"]
    assert client.get("/api/instance").json()["demo"]["resume"]["fund"] == code
    assert client.post("/api/auth/logout").status_code == 204  # or the session timed out
    assert client.get("/api/funds").status_code == 401

    resumed = client.post("/api/demo/resume", json={})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["fund"] == code and resumed.json()["user"]["role"] == "analyst"
    assert [f["code"] for f in client.get("/api/funds").json()] == [code]

    # Another browser has no way back into it.
    stranger = visitors()
    assert stranger.get("/api/instance").json()["demo"]["resume"] is None
    assert stranger.post("/api/demo/resume", json={}).status_code == 404
    stranger.cookies.set("rp_demo", "guessed-token")
    assert stranger.post("/api/demo/resume", json={}).status_code == 404


def test_an_expired_fund_cannot_be_resumed(visitors, db_engine):
    client = visitors()
    code = start(client)["fund"]
    with factory(db_engine)() as session, session.begin():
        session.execute(select(Fund).where(Fund.code == code)).scalar_one().demo_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1))
    assert client.get("/api/instance").json()["demo"]["resume"] is None
    refused = client.post("/api/demo/resume", json={})
    assert refused.status_code == 404 and "Start a new demo" in refused.json()["detail"]


def test_one_click_users_cannot_sign_in_with_a_password(visitors):
    client = visitors()
    username = start(client)["user"]["username"]
    response = TestClient(client.app).post("/api/auth/login", json={"username": username, "password": "x" * 16})
    assert response.status_code == 401


def test_a_real_user_cannot_use_the_switcher(visitors, make_user):
    make_user("approver1", "approver")
    client = visitors()
    start(client)
    other = visitors()
    response = other.post("/api/auth/login", json={"username": "approver1", "password": "Ledger-Walrus-4817"})
    assert response.status_code == 200
    other.headers["X-CSRF-Token"] = other.cookies["rp_csrf"]
    me = client.get("/api/auth/me").json()
    target = me["demo"]["users"][1]["username"]
    assert other.post("/api/demo/switch", json={"username": target}).status_code == 403
    assert other.post("/api/demo/next-day").status_code == 403


# --------------------------------------------------------------------------- carrying on


def work_the_day(client: TestClient, code: str, as_of: str) -> None:
    """Decide the day as the visitor would: Priya the cases, Tom the escalated ones."""
    switch(client, "priya")
    for case in client.get(f"/api/funds/{code}/days/{as_of}/cases", params={"status": "PENDING"}).json():
        if not case["escalated"]:
            r = client.post(f"/api/funds/{code}/cases/{case['case_id']}/decision",
                            json={"decision": "approve", "version": case["version"]})
            assert r.status_code == 200, r.text
    switch(client, "tom")
    for case in client.get(f"/api/funds/{code}/days/{as_of}/cases").json():
        if case["escalated"]:
            r = client.post(f"/api/funds/{code}/cases/{case['case_id']}/decision",
                            json={"decision": "approve", "version": case["version"]})
            assert r.status_code == 200, r.text


def test_visitor_signs_off_with_four_eyes_and_generates_the_next_day(visitors, demo_app, db_engine):
    client = visitors()
    code = start(client)["fund"]
    assert client.post("/api/demo/next-day").status_code == 409  # Friday is not signed off yet

    work_the_day(client, code, FRIDAY)
    refused = client.post(f"/api/funds/{code}/days/{FRIDAY}/signoff")  # Tom decided: four-eyes
    assert refused.status_code == 409
    assert "FOUR_EYES" in {r["code"] for r in refused.json()["detail"]["reasons"]}
    switch(client, "ann")
    signed = client.post(f"/api/funds/{code}/days/{FRIDAY}/signoff")
    assert signed.status_code == 200, signed.text

    switch(client, "vic")
    assert client.post("/api/demo/next-day").status_code == 403  # viewers cannot
    switch(client, "priya")
    generated = client.post("/api/demo/next-day")
    assert generated.status_code == 200, generated.text
    monday = generated.json()["as_of"]
    assert monday == str(demo.demo_days()[demo.DEMO_WEEK].as_of)
    assert client.get(f"/api/funds/{code}/days/{monday}").json()["status"] == "running"
    assert jobs.work_one(factory(db_engine), "test-worker") == generated.json()["job_id"]
    day = client.get(f"/api/funds/{code}/days/{monday}").json()
    assert day["status"] == "ready" and day["summary"]["carried_cases"] > 0
    assert client.get(f"/api/jobs/{generated.json()['job_id']}").json()["status"] == "done"
    assert client.post("/api/demo/next-day").status_code == 409  # Monday is not signed off


def test_the_sequence_ends_cleanly(demo_db, db_engine):
    with factory(db_engine)() as session, session.begin():
        fund, team = demo.create_demo_fund(session, "visitor", max_funds=10, per_hour=10)
        last = demo.demo_days()[-1].as_of
        friday = session.execute(
            select(BusinessDay).where(BusinessDay.fund_id == fund.id, BusinessDay.as_of == demo.demo_days()[4].as_of)
        ).scalar_one()
        friday.status, friday.as_of = "signed_off", last  # as if the visitor had worked to the end
        session.flush()
        with pytest.raises(Exception) as refused:
            demo.generate_next_day(session, fund, team[demo.ANALYST])
        assert refused.value.status_code == 409 and str(last) in refused.value.detail
        session.rollback()


# --------------------------------------------------------------------------- uploads and the mode guard


def test_uploads_are_switched_off_on_the_server(visitors, day_files):
    client = visitors()
    code = start(client)["fund"]
    files = [("files", ("fund.csv", day_files[0]["fund"], "text/csv"))]
    response = client.post(f"/api/funds/{code}/days/2026-11-16/files", files=files)
    assert response.status_code == 403 and response.json()["detail"] == "Uploads are switched off in the demo."
    intake = client.get(f"/api/funds/{code}/days/2026-11-16/intake").json()
    assert intake["blocked"]["code"] == "UPLOADS_OFF"


def test_demo_routes_do_not_exist_on_a_real_instance(client):
    assert client.get("/api/instance").json() == {"mode": "real"}
    assert client.post("/api/demo", json={}).status_code == 404


def test_instance_reports_the_demo(visitors):
    body = visitors().get("/api/instance").json()
    assert body["mode"] == "demo"
    assert body["demo"]["expires_after_hours"] == 24 and body["demo"]["week"] == WEEK


def test_instance_mode_guard(pg_uri, pg_dir, demo_db, clean_db):
    # The database is a demo database now: a real instance refuses it, and so does migrate.
    with pytest.raises(RuntimeError, match="demo database"):
        create_app(make_settings(pg_uri, pg_dir, mode="real"))
    with pytest.raises(RuntimeError, match="demo database"):
        cli.migrate(make_settings(pg_uri, pg_dir, mode="real"))


def test_demo_instance_refuses_a_real_database(pg_uri, pg_dir, clean_db):
    with pytest.raises(RuntimeError, match="real database"):
        create_app(make_settings(pg_uri, pg_dir, mode="demo"))


def test_demo_instance_loads_the_ai_cache(demo_app, db_engine):
    from reconpilot_web.models import AICacheEntry

    with factory(db_engine)() as session:
        held = session.execute(select(func.count()).select_from(AICacheEntry)).scalar_one()
    assert held == len(demo_cache_meta()["responses"]) > 0


# --------------------------------------------------------------------------- expiry and limits


def test_use_keeps_a_fund_alive(visitors, db_engine):
    client = visitors()
    code = start(client)["fund"]
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    with factory(db_engine)() as session, session.begin():
        session.execute(select(Fund).where(Fund.code == code)).scalar_one().demo_expires_at = soon
    client.get("/api/funds")
    with factory(db_engine)() as session:
        expires = session.execute(select(Fund.demo_expires_at).where(Fund.code == code)).scalar_one()
    assert expires > datetime.now(timezone.utc) + timedelta(hours=23, minutes=58)


def test_expired_funds_are_deleted_with_everything_in_them(visitors, db_engine):
    old, current = visitors(), visitors()
    old_code, current_code = start(old)["fund"], start(current)["fund"]
    with factory(db_engine)() as session, session.begin():
        fund = session.execute(select(Fund).where(Fund.code == old_code)).scalar_one()
        fund.demo_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        old_id = fund.id
        day_ids = list(session.execute(select(BusinessDay.id).where(BusinessDay.fund_id == old_id)).scalars())

    assert demo.cleanup_once(factory(db_engine)) == [old_code]

    assert old.get("/api/funds").status_code == 401  # its users and sessions went with it
    assert current.get("/api/funds").json()[0]["code"] == current_code
    with factory(db_engine)() as session:
        for model, column in ((Fund, Fund.id), (BusinessDay, BusinessDay.fund_id), (CaseRow, CaseRow.fund_id),
                              (Decision, Decision.fund_id), (User, User.demo_fund_id)):
            assert session.execute(select(func.count()).select_from(model).where(column == old_id)).scalar_one() == 0
        jobs_left = session.execute(
            select(func.count(Job.id)).where(Job.payload["business_day_id"].as_integer().in_(day_ids))
        ).scalar_one()
        assert jobs_left == 0
        assert session.execute(select(func.count(UserSession.id))).scalar_one() == 1  # the current visitor's
        expired = session.execute(
            select(AuditEntry.payload).where(AuditEntry.action == "DEMO_FUND_EXPIRED")).scalars().all()
        assert [e["code"] for e in expired] == [old_code]
        assert verify_chain(session) == (True, None)
    assert demo.cleanup_once(factory(db_engine)) == []


def test_starting_a_demo_is_rate_limited(demo_settings):
    application = create_app(dataclasses.replace(demo_settings, demo_creations_per_hour=2))
    try:
        with TestClient(application) as c:
            assert c.post("/api/demo", json={}).status_code == 200
            assert c.post("/api/demo", json={}).status_code == 200
            refused = c.post("/api/demo", json={})
            assert refused.status_code == 429 and "last hour" in refused.json()["detail"]
    finally:
        application.state.engine.dispose()


def test_live_demo_funds_are_capped(demo_settings, db_engine):
    application = create_app(dataclasses.replace(demo_settings, demo_max_funds=1, demo_creations_per_hour=10))
    try:
        with TestClient(application) as first, TestClient(application) as second:
            code = start(first)["fund"]
            full = second.post("/api/demo", json={})
            assert full.status_code == 503 and "full" in full.json()["detail"]
            # An expired fund no longer counts: the next visitor gets its place.
            with factory(db_engine)() as session, session.begin():
                session.execute(select(Fund).where(Fund.code == code)).scalar_one().demo_expires_at = (
                    datetime.now(timezone.utc) - timedelta(seconds=1))
            assert second.post("/api/demo", json={}).status_code == 200
    finally:
        application.state.engine.dispose()


def test_start_needs_json_so_a_cross_site_form_cannot_start_one(visitors):
    response = visitors().post("/api/demo", data={"x": "1"})
    assert response.status_code == 422


def test_demo_cleanup_command(demo_settings, monkeypatch, capsys, db_engine):
    with factory(db_engine)() as session, session.begin():
        fund, _ = demo.create_demo_fund(session, "visitor", max_funds=10, per_hour=10)
        fund.demo_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        code = fund.code
    for key, value in {"RP_DATABASE_URL": demo_settings.database_url, "RP_MODE": "demo",
                       "RP_DATA_DIR": str(demo_settings.data_dir)}.items():
        monkeypatch.setenv(key, value)
    assert cli.main(["demo-cleanup"]) == 0
    assert code in capsys.readouterr().out
    with factory(db_engine)() as session:
        assert session.execute(select(func.count(Fund.id))).scalar_one() == 0


def test_the_cache_answers_every_question_of_the_whole_sequence(demo_app, db_engine):
    """Every case on every day a visitor can reach is answered from the committed cache.

    Fails when something changes the AI's prompts (the evidence, the prompt version, the
    seed): rebuild the cache with ``scripts/build_demo_ai_cache.py`` then.
    """
    from reconpilot_web.release import sign_off_day

    days = demo.demo_days()
    with factory(db_engine)() as session, session.begin():
        fund, team = demo.create_demo_fund(session, "visitor", max_funds=10, per_hour=10)
        for previous, day in zip(days[demo.DEMO_WEEK - 1:], days[demo.DEMO_WEEK:]):
            demo.review_day(session, fund, previous, team)
            sign_off_day(session, fund, previous.as_of, team[demo.SIGNER])
            demo.load_demo_day(session, fund, day, team[demo.ANALYST])
            demo.run_inline(session, fund, day.as_of, team[demo.ANALYST])
        calls = list(session.execute(
            select(AuditEntry.payload).where(AuditEntry.fund_id == fund.id, AuditEntry.action == "AI_CALL")
        ).scalars())
    assert len(calls) >= demo.DEMO_HORIZON
    assert [c["case_id"] for c in calls if c["fallback_reason"] == aicache.CACHE_MISS] == []
    assert all(c["cached"] for c in calls)
    assert any(c["disagrees"] for c in calls)  # the AI's second opinion shows in the demo


def test_serve_demo_keeps_its_own_database_folder():
    from pathlib import Path

    from reconpilot_web.config import load_settings

    settings = cli.demo_settings(load_settings({}), env={})
    assert settings.mode == "demo" and settings.data_dir == Path(".rp_data") / "demo"
    assert settings.ai_cache_dir == Path(".rp_data") / "demo" / "ai_cache"
    chosen = cli.demo_settings(load_settings({"RP_DATA_DIR": "/srv/demo"}), env={"RP_DATA_DIR": "/srv/demo"})
    assert chosen.data_dir == Path("/srv/demo")
