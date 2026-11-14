"""Each user's preferred fund: stored on the server, per user, and cleared with the fund."""

from __future__ import annotations

from sqlalchemy import delete, select

from reconpilot_web.models import Fund, User

from .conftest import FUND_CODE

PREFS = "/api/auth/me/preferences"


def test_preferences_need_sign_in(client, fund):
    assert client.get(PREFS).status_code == 401
    assert client.put(PREFS, json={"fund": FUND_CODE}).status_code in (401, 403)


def test_no_fund_until_one_is_chosen(make_client, users, fund):
    assert make_client("analyst1").get(PREFS).json() == {"fund": None}


def test_chosen_fund_is_kept_per_user_across_sessions(make_client, users, make_fund):
    make_fund()
    make_fund("INC2", name="Income Fund")
    analyst = make_client("analyst1")
    response = analyst.put(PREFS, json={"fund": "inc2"})
    assert response.status_code == 200, response.text
    assert response.json() == {"fund": "INC2"}

    # A new browser, a new session: the choice follows the user.
    assert make_client("analyst1").get(PREFS).json() == {"fund": "INC2"}
    # Every user keeps their own.
    assert make_client("approver1").get(PREFS).json() == {"fund": None}

    assert analyst.put(PREFS, json={"fund": None}).json() == {"fund": None}
    assert make_client("analyst1").get(PREFS).json() == {"fund": None}


def test_viewer_may_choose_a_fund(make_client, users, fund):
    viewer = make_client("viewer1")
    assert viewer.put(PREFS, json={"fund": FUND_CODE}).json() == {"fund": FUND_CODE}


def test_unknown_fund_refused(make_client, users, fund):
    analyst = make_client("analyst1")
    response = analyst.put(PREFS, json={"fund": "NOPE"})
    assert response.status_code == 404
    assert analyst.get(PREFS).json() == {"fund": None}


def test_change_needs_csrf_token(make_client, users, fund):
    analyst = make_client("analyst1")
    del analyst.headers["X-CSRF-Token"]
    assert analyst.put(PREFS, json={"fund": FUND_CODE}).status_code == 403
    assert analyst.get(PREFS).json() == {"fund": None}


def test_removed_fund_clears_the_choice(make_client, users, make_fund, db_session):
    make_fund()
    make_fund("INC2", name="Income Fund")
    analyst = make_client("analyst1")
    analyst.put(PREFS, json={"fund": "INC2"})
    db_session.execute(delete(Fund).where(Fund.code == "INC2"))
    db_session.commit()
    stored = db_session.execute(select(User.preferred_fund_id).where(User.username == "analyst1")).scalar_one()
    assert stored is None
    assert analyst.get(PREFS).json() == {"fund": None}


def test_me_is_unchanged(make_client, users, fund):
    analyst = make_client("analyst1")
    analyst.put(PREFS, json={"fund": FUND_CODE})
    assert analyst.get("/api/auth/me").json() == {
        "username": "analyst1", "display_name": "Priya Shah", "role": "analyst", "is_admin": False,
    }
