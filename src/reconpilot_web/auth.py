"""Built-in accounts: sign-in, server-side sessions, CSRF protection, lockout and roles.

Sessions
    Signing in creates a row in ``sessions`` holding the SHA-256 of a random
    token; the token itself lives only in the ``rp_session`` cookie (httpOnly,
    SameSite=Lax, Secure when ``RP_COOKIE_SECURE=1``). A session ends when it is
    signed out (revoked), after 30 minutes without a request, or 12 hours after
    sign-in, whichever comes first. A revoked or expired token is refused on
    every route, so a copied cookie is useless once its session has ended.

CSRF
    Each session has a CSRF token, sent in the readable ``rp_csrf`` cookie. Every
    POST, PUT, PATCH and DELETE must echo it in the ``X-CSRF-Token`` header, and
    it must match both the cookie and the session's own token. Sign-in is the one
    exception, because it is what issues the token; it accepts JSON only, which a
    cross-site form cannot send.

Usernames
    Usernames are case-insensitive: they are stored in lower case, and sign-in
    lower-cases what is typed, so "Analyst1" and "analyst1" are one account.

Signing in again from a browser that still holds a session revokes that
session, so one browser never keeps two live sessions.

Lockout
    Five consecutive failed sign-ins lock the account for 15 minutes. While it is
    locked even the right password is refused with 423.

Roles are checked here, on the server, from the session: ``require_roles``
answers 403 to anyone else, and ``require_admin`` to anyone without the admin flag.

Demo visitors (spec section 11)
    A one-click demo user belongs to one visitor fund (``users.demo_fund_id``) and has
    no password, so it can only be entered through the demo's own routes. Every
    request it makes is scoped to that fund: ``current_user`` records the scope on the
    request's database session (``FUND_SCOPE``), ``funds.get_fund`` answers 404 for any
    other fund, and lists (funds, jobs, the audit log) leave other funds out. Each of
    its requests also keeps the fund alive for ``DEMO_TTL`` more.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.models import ROLES, Fund, User, UserSession
from reconpilot_web.security import (
    check_password_policy,
    hash_password,
    needs_rehash,
    new_token,
    token_digest,
    tokens_equal,
    verify_password,
)

SESSION_COOKIE = "rp_session"
CSRF_COOKIE = "rp_csrf"
CSRF_HEADER = "X-CSRF-Token"

IDLE_TIMEOUT = timedelta(minutes=30)
ABSOLUTE_TIMEOUT = timedelta(hours=12)
MAX_FAILED_LOGINS = 5
LOCKOUT_PERIOD = timedelta(minutes=15)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# Sign-in and starting or resuming a demo issue the CSRF token, so they cannot need one; all take JSON only.
CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login", "/api/demo", "/api/demo/resume"})

SYSTEM_ACTOR = "reconpilot-web"
SYSTEM_ROLE = "system"

# The key in a request's ``Session.info`` holding the one fund a demo user may see.
FUND_SCOPE = "fund_scope"
# A demo fund lives this long after its last use (spec section 11) ...
DEMO_TTL = timedelta(hours=24)
# ... and its expiry is moved on at most this often, not on every request.
DEMO_TOUCH_EVERY = timedelta(minutes=1)

# Verified against when the username is unknown, so a miss takes as long as a wrong password.
_DUMMY_HASH: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(new_token())
    return _DUMMY_HASH


# --------------------------------------------------------------------------- database session


def get_db(request: Request) -> Iterator[Session]:
    """A database session for one request. Handlers commit their own work."""
    session = request.app.state.session_factory()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


# --------------------------------------------------------------------------- users


def normalise_username(username: str) -> str:
    """The stored form of a username: trimmed and lower-cased."""
    return username.strip().lower()


def fund_scope(db: Session) -> int | None:
    """The id of the one fund this request's user may see, or ``None`` for a real user."""
    return db.info.get(FUND_SCOPE)


def touch_demo_fund(db: Session, fund_id: int, now: datetime) -> None:
    """Keep a demo fund alive for ``DEMO_TTL`` from ``now`` (written at most once a minute)."""
    fund = db.get(Fund, fund_id)
    if fund is not None and fund.is_demo and (
        fund.demo_expires_at is None or fund.demo_expires_at < now + DEMO_TTL - DEMO_TOUCH_EVERY
    ):
        fund.demo_expires_at = now + DEMO_TTL


def demo_payload(db: Session, user: User) -> dict[str, Any] | None:
    """A demo user's fund, its expiry and the fund's one-click users (for the role switcher)."""
    if user.demo_fund_id is None:
        return None
    fund = db.get(Fund, user.demo_fund_id)
    if fund is None:
        return None
    team = db.execute(select(User).where(User.demo_fund_id == fund.id).order_by(User.id)).scalars().all()
    return {
        "fund": fund.code,
        "fund_name": fund.name,
        "expires_at": fund.demo_expires_at.isoformat() if fund.demo_expires_at else None,
        "users": [
            {"username": u.username, "display_name": u.display_name or u.username, "role": u.role} for u in team
        ],
    }


def user_payload(user: User) -> dict[str, Any]:
    return {
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "is_admin": user.is_admin,
    }


def create_user(
    session: Session,
    username: str,
    password: str,
    role: str,
    *,
    is_admin: bool = False,
    display_name: str = "",
    actor: str = SYSTEM_ACTOR,
    actor_role: str = SYSTEM_ROLE,
) -> User:
    """Add a user and audit ``USER_CREATED`` in the caller's transaction.

    Raises ``ValueError`` for an unknown role, a taken username or a password the
    policy refuses (the message lists every problem).
    """
    username = normalise_username(username)
    if not username or len(username) > 64:
        raise ValueError("Username must be 1 to 64 characters.")
    if not username.isprintable():
        raise ValueError("Username cannot contain control characters.")
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}.")
    problems = check_password_policy(password)
    if problems:
        raise ValueError(" ".join(problems))
    if session.execute(select(User.id).where(User.username == username)).first():
        raise ValueError(f"User {username!r} already exists.")
    user = User(
        username=username,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role=role,
        is_admin=is_admin,
    )
    session.add(user)
    session.flush()
    DbAuditLog(session).append(
        actor, actor_role, "USER_CREATED", {"username": username, "role": role, "is_admin": is_admin}
    )
    return user


# --------------------------------------------------------------------------- dependencies


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _load_session(db: Session, token: str | None) -> UserSession | None:
    if not token:
        return None
    return db.execute(
        select(UserSession).where(UserSession.token_hash == token_digest(token))
    ).scalar_one_or_none()


def _session_is_live(row: UserSession, now: datetime) -> bool:
    return (
        row.revoked_at is None
        and row.expires_at > now
        and row.created_at + ABSOLUTE_TIMEOUT > now
        and row.last_seen_at + IDLE_TIMEOUT > now
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The signed-in user. 401 if the session is missing, expired, revoked or the user inactive."""
    now = _now()
    row = _load_session(db, request.cookies.get(SESSION_COOKIE))
    user = db.get(User, row.user_id) if row is not None else None
    if row is None or user is None or not _session_is_live(row, now) or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    row.last_seen_at = now
    if user.demo_fund_id is not None:
        db.info[FUND_SCOPE] = user.demo_fund_id
        touch_demo_fund(db, user.demo_fund_id, now)
    db.commit()
    request.state.user_session = row
    request.state.user = user
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """A dependency allowing only users whose role is one of ``roles`` (403 otherwise)."""
    unknown = set(roles) - set(ROLES)
    if unknown:
        raise ValueError(f"unknown roles: {', '.join(sorted(unknown))}")

    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot do this.")
        return user

    dependency.__name__ = f"require_roles_{'_'.join(roles)}"
    return dependency


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an administrator can do this.")
    return user


def csrf_protect(request: Request, db: Session = Depends(get_db)) -> None:
    """Refuse a state-changing request (403) whose ``X-CSRF-Token`` header does not match.

    The header must equal the ``rp_csrf`` cookie and, when a session cookie is sent,
    the token stored for that session. Applied to the whole app; safe methods and
    sign-in pass through.
    """
    if request.method in SAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
        return
    header = request.headers.get(CSRF_HEADER)
    if not tokens_equal(header, request.cookies.get(CSRF_COOKIE)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token.")
    row = _load_session(db, request.cookies.get(SESSION_COOKIE))
    if row is not None and not tokens_equal(header, row.csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token.")


# --------------------------------------------------------------------------- routes

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def set_session_cookies(response: Response, request: Request, token: str, csrf: str) -> None:
    secure = request.app.state.settings.cookie_secure
    max_age = int(ABSOLUTE_TIMEOUT.total_seconds())
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, path="/", httponly=True, samesite="lax", secure=secure
    )
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, path="/", httponly=False, samesite="lax", secure=secure
    )


def _clear_cookies(response: Response, request: Request) -> None:
    secure = request.app.state.settings.cookie_secure
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=secure)
    response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, samesite="lax", secure=secure)


def _refuse(db: Session, status_code: int, detail: str) -> HTTPException:
    """Commit the failure bookkeeping and audit, then return the error to raise."""
    db.commit()
    return HTTPException(status_code, detail)


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    now = _now()
    ip = _client_ip(request)
    username = normalise_username(body.username)
    audit = DbAuditLog(db)
    bad_credentials = "Wrong username or password."

    user = None
    if username.isprintable() and len(username) <= 64:  # no stored username is longer or holds NUL
        user = db.execute(
            select(User).where(User.username == username).with_for_update()
        ).scalar_one_or_none()
    if user is None or user.password_hash is None:
        verify_password(_dummy_hash(), body.password)
        audit.append(username[:128], "", "SIGN_IN_FAILED", {"reason": "unknown user", "ip": ip})
        raise _refuse(db, status.HTTP_401_UNAUTHORIZED, bad_credentials)

    audit = DbAuditLog(db, fund_id=user.demo_fund_id)
    if user.locked_until is not None and user.locked_until > now:
        audit.append(user.username, user.role, "SIGN_IN_FAILED", {"reason": "locked", "ip": ip})
        raise _refuse(db, status.HTTP_423_LOCKED, _locked_message(user.locked_until, now))

    if not verify_password(user.password_hash, body.password):
        user.failed_logins += 1
        audit.append(
            user.username, user.role, "SIGN_IN_FAILED",
            {"reason": "wrong password", "failed_logins": user.failed_logins, "ip": ip},
        )
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.locked_until = now + LOCKOUT_PERIOD
            audit.append(
                user.username, user.role, "ACCOUNT_LOCKED",
                {"failed_logins": user.failed_logins, "locked_until": user.locked_until.isoformat(), "ip": ip},
            )
            user.failed_logins = 0
            raise _refuse(db, status.HTTP_423_LOCKED, _locked_message(user.locked_until, now))
        raise _refuse(db, status.HTTP_401_UNAUTHORIZED, bad_credentials)

    if not user.is_active:
        audit.append(user.username, user.role, "SIGN_IN_FAILED", {"reason": "inactive", "ip": ip})
        raise _refuse(db, status.HTTP_401_UNAUTHORIZED, bad_credentials)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    token, csrf = open_session(db, request, user, now)
    audit.append(user.username, user.role, "SIGN_IN", {"ip": ip})
    db.commit()
    set_session_cookies(response, request, token, csrf)
    return {"user": user_payload(user)}


def open_session(db: Session, request: Request, user: User, now: datetime) -> tuple[str, str]:
    """Start a session for ``user`` in ``db``'s transaction, ending any this browser still holds.

    Returns ``(session token, CSRF token)`` for ``set_session_cookies`` once the caller commits.
    """
    previous = _load_session(db, request.cookies.get(SESSION_COOKIE))
    if previous is not None and previous.revoked_at is None:
        previous.revoked_at = now
    token, csrf = new_token(), new_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_digest(token),
            csrf_token=csrf,
            created_at=now,
            last_seen_at=now,
            expires_at=now + ABSOLUTE_TIMEOUT,
            ip_address=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:512] or None,
        )
    )
    return token, csrf


def _locked_message(until: datetime, now: datetime) -> str:
    minutes = max(1, int((until - now).total_seconds() + 59) // 60)
    return f"Account locked after {MAX_FAILED_LOGINS} failed sign-ins. Try again in {minutes} minutes."


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    row: UserSession = request.state.user_session
    row.revoked_at = _now()
    DbAuditLog(db, fund_id=user.demo_fund_id).append(user.username, user.role, "SIGN_OUT", {"ip": _client_ip(request)})
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookies(response, request)
    return response


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The signed-in user; a demo user also gets ``demo`` (their fund and its one-click users)."""
    demo = demo_payload(db, user)
    return {**user_payload(user), "demo": demo} if demo is not None else user_payload(user)
