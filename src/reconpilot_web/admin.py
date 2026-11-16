"""Administration (spec sections 1, 9 and 10): users, funds and each fund's AI switch.

Every route here needs the admin flag (``auth.require_admin``), checked on the server.
Demo users and demo funds are not administered here: they come and go with their visitor.

Users
    Create (the password policy applies), change the display name, role or admin flag,
    deactivate and reactivate, reset the password, and unlock an account locked after
    failed sign-ins. A role, admin-flag or password change and a deactivation revoke every
    live session of that user, so the change takes effect at once, not at their next
    sign-in. An administrator cannot change their own account here (another administrator
    must), so the last active administrator can never lock everyone out. Each change is
    one audit entry: ``USER_CREATED``, ``USER_RENAMED``, ``USER_ROLE_CHANGED``,
    ``USER_ADMIN_CHANGED``, ``USER_DEACTIVATED``, ``USER_REACTIVATED``, ``PASSWORD_RESET``,
    ``ACCOUNT_UNLOCKED``, each saying how many sessions it revoked.

Funds
    Create a fund, rename it, change its settings (materiality, escalation and SLA days,
    the release checks) and its non-business dates. Settings apply from the fund's next
    run. A non-business date can be added or removed only after the fund's latest loaded
    day (an earlier change would rewrite the calendar that loaded days were worked on).
    Audited as ``FUND_CREATED``, ``FUND_SETTINGS_CHANGED`` (each setting from and to) and
    ``FUND_CALENDAR_CHANGED`` (dates added and removed).

The AI switch (spec section 9, engine change 4)
    In real mode AI is off for every fund until an administrator switches it on. Switching
    on names a provider (or the server's default), needs that provider configured on the
    server (a key, or for ``openai_compatible`` a base URL) and needs the administrator to
    acknowledge where the evidence goes: to a public provider it leaves the firm; to a
    private endpoint it goes to the host shown. ``AI_SWITCHED_ON`` and ``AI_SWITCHED_OFF``
    record the provider and model. Keys never leave the server and are never shown.
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from reconpilot.ai import COMPATIBLE_ENV, COMPATIBLE_PROVIDER, DEFAULT_MODELS, KEY_ENV
from reconpilot_web import runner
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    create_user,
    get_db,
    normalise_username,
    require_admin,
)
from reconpilot_web.funds import (
    DEFAULT_FUND_SETTINGS,
    create_fund,
    fund_detail,
    fund_settings,
    get_fund,
    latest_day,
    validate_settings,
)
from reconpilot_web.models import ROLES, Fund, User, UserSession
from reconpilot_web.security import check_password_policy, hash_password

AI_PROVIDERS = (*DEFAULT_MODELS, COMPATIBLE_PROVIDER)
PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    COMPATIBLE_PROVIDER: "Private endpoint (OpenAI-compatible)",
}

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# --------------------------------------------------------------------------- users


def live_sessions(db: Session, user: User, now: datetime) -> int:
    """How many of the user's sessions could still be used (not revoked, not timed out)."""
    return db.execute(
        select(func.count()).select_from(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            UserSession.created_at > now - ABSOLUTE_TIMEOUT,
            UserSession.last_seen_at > now - IDLE_TIMEOUT,
        )
    ).scalar_one()


def revoke_sessions(db: Session, user: User, now: datetime) -> int:
    """End every session the user still holds; how many were ended."""
    result = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount or 0


def admin_user_payload(db: Session, user: User, now: datetime) -> dict[str, Any]:
    locked = user.locked_until is not None and user.locked_until > now
    return {
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "locked": locked,
        "locked_until": _iso(user.locked_until) if locked else None,
        "failed_logins": user.failed_logins,
        "last_login_at": _iso(user.last_login_at),
        "created_at": _iso(user.created_at),
        "live_sessions": live_sessions(db, user, now),
    }


def _target_user(db: Session, username: str, admin: User) -> User:
    """The (real) user to change, locked for the change; 404 if none, 409 if it is the admin themselves."""
    user = db.execute(
        select(User).where(User.username == normalise_username(username), User.demo_fund_id.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No user {username}.")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "You cannot change your own account here; ask another administrator.")
    return user


class CreateUserRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    role: str
    display_name: str = Field("", max_length=128)
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(None, max_length=128)
    role: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None


class PasswordRequest(BaseModel):
    password: str = Field(max_length=256)


@router.get("/users")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    """Every real user (demo visitors' one-click users are left out), by username."""
    now = _now()
    users = db.execute(
        select(User).where(User.demo_fund_id.is_(None)).order_by(User.username)
    ).scalars().all()
    return [admin_user_payload(db, u, now) for u in users]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def add_user(body: CreateUserRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        user = create_user(db, body.username, body.password, body.role, is_admin=body.is_admin,
                           display_name=body.display_name, actor=admin.username, actor_role=admin.role)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    db.commit()
    return admin_user_payload(db, user, _now())


@router.patch("/users/{username}")
def change_user(
    username: str, body: UpdateUserRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    """Change a user's display name, role, admin flag or whether they are active (only what is sent)."""
    now = _now()
    user = _target_user(db, username, admin)
    audit = DbAuditLog(db)
    sent = body.model_fields_set

    if "role" in sent and body.role not in ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Role must be one of {', '.join(ROLES)}.")
    if "display_name" in sent and body.display_name is not None:
        name = body.display_name.strip()
        if not name.isprintable():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The display name must be printable.")
        if name != user.display_name:
            audit.append(admin.username, admin.role, "USER_RENAMED",
                         {"username": user.username, "from": user.display_name, "to": name})
            user.display_name = name
    if "role" in sent and body.role != user.role:
        revoked = revoke_sessions(db, user, now)
        audit.append(admin.username, admin.role, "USER_ROLE_CHANGED",
                     {"username": user.username, "from": user.role, "to": body.role, "sessions_revoked": revoked})
        user.role = body.role
    if "is_admin" in sent and body.is_admin is not None and body.is_admin != user.is_admin:
        revoked = revoke_sessions(db, user, now)
        audit.append(admin.username, admin.role, "USER_ADMIN_CHANGED",
                     {"username": user.username, "is_admin": body.is_admin, "sessions_revoked": revoked})
        user.is_admin = body.is_admin
    if "is_active" in sent and body.is_active is not None and body.is_active != user.is_active:
        if body.is_active:
            audit.append(admin.username, admin.role, "USER_REACTIVATED", {"username": user.username})
        else:
            revoked = revoke_sessions(db, user, now)
            audit.append(admin.username, admin.role, "USER_DEACTIVATED",
                         {"username": user.username, "sessions_revoked": revoked})
        user.is_active = body.is_active
    db.commit()
    return admin_user_payload(db, user, now)


@router.post("/users/{username}/password")
def reset_password(
    username: str, body: PasswordRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    """Set a new password (the policy applies), end the user's sessions and clear any lockout."""
    now = _now()
    user = _target_user(db, username, admin)
    problems = check_password_policy(body.password)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, " ".join(problems))
    user.password_hash = hash_password(body.password)
    user.failed_logins = 0
    user.locked_until = None
    revoked = revoke_sessions(db, user, now)
    DbAuditLog(db).append(admin.username, admin.role, "PASSWORD_RESET",
                          {"username": user.username, "sessions_revoked": revoked})
    db.commit()
    return admin_user_payload(db, user, now)


@router.post("/users/{username}/unlock")
def unlock_account(username: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Lift a lockout after failed sign-ins before it runs out; 409 if the account is not locked."""
    now = _now()
    user = _target_user(db, username, admin)
    if user.locked_until is None or user.locked_until <= now:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{user.username} is not locked.")
    was = user.locked_until
    user.locked_until = None
    user.failed_logins = 0
    DbAuditLog(db).append(admin.username, admin.role, "ACCOUNT_UNLOCKED",
                          {"username": user.username, "was_locked_until": was.isoformat()})
    db.commit()
    return admin_user_payload(db, user, now)


# --------------------------------------------------------------------------- AI providers


def compatible_host() -> str | None:
    """The host of the private endpoint (never its key), or ``None`` when none is configured."""
    base = os.environ.get(COMPATIBLE_ENV["base_url"], "").strip()
    return (urllib.parse.urlsplit(base).netloc or None) if base else None


def provider_info(name: str) -> dict[str, Any]:
    """What the server has for ``name``: configured or not, the model a run would use, where it sends evidence."""
    problem = None
    try:
        client = runner.ai_client(name)
    except ValueError as exc:  # a malformed private-endpoint configuration
        client, problem = None, str(exc)
    private = name == COMPATIBLE_PROVIDER
    if client is None and problem is None:
        needs = COMPATIBLE_ENV["base_url"] if private else KEY_ENV[name]
        problem = f"Not configured on the server: set {needs}."
    return {
        "provider": name,
        "label": PROVIDER_LABELS[name],
        "configured": client is not None,
        "model": client.model if client is not None else None,
        "private": private,
        "endpoint": compatible_host() if private else None,
        "problem": problem,
    }


def default_provider() -> str | None:
    """The provider a fund with no choice of its own uses: ``RP_AI_PROVIDER``, else the first with a key."""
    try:
        client = runner.ai_client(None)
    except ValueError:
        return None
    return client.provider if client is not None else None


def ai_state(fund: Fund) -> dict[str, Any]:
    """The fund's AI switch as the admin page shows it."""
    effective = fund.ai_provider or default_provider()
    info = provider_info(effective) if effective in AI_PROVIDERS else None
    return {
        "enabled": bool(fund_settings(fund)["ai_enabled"]),
        "provider": fund.ai_provider,
        "effective_provider": effective,
        "model": info["model"] if info else None,
    }


@router.get("/ai/providers")
def list_providers(admin: User = Depends(require_admin)) -> dict:
    """Every AI provider the engine knows, whether the server can use it, and the server's default."""
    return {"default": default_provider(), "providers": [provider_info(p) for p in AI_PROVIDERS]}


class AiSwitchRequest(BaseModel):
    enabled: bool
    provider: str | None = None  # ``None``: the server's default
    acknowledged: bool = False  # the administrator has read where the evidence goes


def _admin_fund(db: Session, code: str) -> Fund:
    fund = get_fund(db, code)
    if fund.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No fund {code}.")
    db.refresh(fund, with_for_update=True)
    return fund


@router.put("/funds/{code}/ai")
def switch_ai(code: str, body: AiSwitchRequest, admin: User = Depends(require_admin),
              db: Session = Depends(get_db)) -> dict:
    """Switch the fund's AI second opinion on (with a provider) or off; audited with provider and model."""
    fund = _admin_fund(db, code)
    settings = fund_settings(fund)
    was_on = bool(settings["ai_enabled"])
    audit = DbAuditLog(db, fund_id=fund.id)

    if not body.enabled:
        if not was_on:
            raise HTTPException(status.HTTP_409_CONFLICT, f"AI is already off for {fund.code}.")
        before = ai_state(fund)
        fund.settings = {**(fund.settings or {}), "ai_enabled": False}
        audit.append(admin.username, admin.role, "AI_SWITCHED_OFF", {
            "provider": before["effective_provider"], "model": before["model"],
        })
        db.commit()
        return {**fund_detail(db, fund), "ai": ai_state(fund)}

    if body.provider is not None and body.provider not in AI_PROVIDERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Provider must be one of {', '.join(AI_PROVIDERS)}, or none for the server's default.")
    effective = body.provider or default_provider()
    if effective is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The server has no AI provider configured; set a provider key first.")
    info = provider_info(effective)
    if not info["configured"]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{info['label']}: {info['problem']}")
    if was_on and fund.ai_provider == body.provider:
        raise HTTPException(status.HTTP_409_CONFLICT, f"AI is already on for {fund.code} with that provider.")
    if not body.acknowledged:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Confirm that the day's evidence (positions, trades, prices and cash for each case) will be sent to "
            + (f"the private endpoint at {info['endpoint']}." if info["private"] else f"{info['label']}, outside the firm."),
        )
    previous = ai_state(fund) if was_on else None
    fund.ai_provider = body.provider
    fund.settings = {**(fund.settings or {}), "ai_enabled": True}
    entry: dict[str, Any] = {
        "provider": effective,
        "model": info["model"],
        "chosen": "fund" if body.provider else "server default",
        "evidence_sent_to": info["endpoint"] if info["private"] else info["label"],
        "leaves_firm": not info["private"],
    }
    if previous is not None:
        entry["previous_provider"] = previous["effective_provider"]
        entry["previous_model"] = previous["model"]
    audit.append(admin.username, admin.role, "AI_SWITCHED_ON", entry)
    db.commit()
    return {**fund_detail(db, fund), "ai": ai_state(fund)}


# --------------------------------------------------------------------------- funds


class CreateFundRequest(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field(max_length=200)
    start_date: date
    non_business_dates: list[date] = Field(default_factory=list, max_length=1000)
    settings: dict[str, Any] = Field(default_factory=dict)


class UpdateFundRequest(BaseModel):
    name: str | None = Field(None, max_length=200)
    settings: dict[str, Any] | None = None
    non_business_dates: list[date] | None = Field(None, max_length=1000)


def _check_settings_values(checks: dict[str, Any]) -> None:
    """The release checks' values must be numbers the engine can use (``validate_settings`` checks the names)."""
    for key, value in checks.items():
        if key == "price_move_limits":
            if not isinstance(value, dict) or not value:
                raise ValueError("price_move_limits must map each asset class to a fraction, such as 0.10.")
            for asset, limit in value.items():
                if not isinstance(asset, str) or not asset.strip():
                    raise ValueError("price_move_limits needs asset class names.")
                if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0 < limit <= 1:
                    raise ValueError(f"The price-move limit for {asset} must be a fraction above 0 and at most 1.")
        elif key == "max_price_age_days":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("max_price_age_days must be a whole number of days, 0 or more.")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < float("inf"):
            raise ValueError(f"{key} must be a number, 0 or more.")


def _admin_settings(settings: dict[str, Any]) -> None:
    if "ai_enabled" in settings:
        raise ValueError("AI is switched on or off with the AI switch, which records where the evidence goes.")
    _check_settings_values(settings.get("check_settings") or {})


@router.post("/funds", status_code=status.HTTP_201_CREATED)
def add_fund(body: CreateFundRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Create a fund (AI off: it is switched on separately)."""
    try:
        _admin_settings(body.settings)
        fund = create_fund(db, body.code, body.name, body.start_date, non_business_dates=body.non_business_dates,
                           settings=body.settings, created_by=admin)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    db.commit()
    return {**fund_detail(db, fund), "ai": ai_state(fund)}


@router.get("/funds/{code}")
def read_admin_fund(code: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """The fund's detail with its AI switch and the latest loaded day (the calendar's edit horizon)."""
    fund = get_fund(db, code)
    if fund.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No fund {code}.")
    return {**fund_detail(db, fund), "ai": ai_state(fund)}


@router.patch("/funds/{code}")
def change_fund(code: str, body: UpdateFundRequest, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    """Rename the fund, change settings (only the keys sent) or replace its non-business dates.

    ``settings.check_settings``, when sent, replaces the fund's overrides as a whole (``{}``
    returns every release check to the engine's default).
    """
    fund = _admin_fund(db, code)
    audit = DbAuditLog(db, fund_id=fund.id)
    changes: dict[str, dict[str, Any]] = {}

    if body.name is not None:
        name = body.name.strip()
        if not name or not name.isprintable():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fund name must be 1 to 200 printable characters.")
        if name != fund.name:
            changes["name"] = {"from": fund.name, "to": name}
            fund.name = name

    if body.settings is not None:
        current = fund_settings(fund)
        try:
            _admin_settings(body.settings)
            merged = validate_settings({**current, **body.settings})
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
        for key in DEFAULT_FUND_SETTINGS:
            if merged[key] != current[key]:
                changes[key] = {"from": current[key], "to": merged[key]}
        fund.settings = merged

    if changes:
        audit.append(admin.username, admin.role, "FUND_SETTINGS_CHANGED", {"code": fund.code, "changes": changes})

    if body.non_business_dates is not None:
        before = set(fund.non_business_dates or ())
        after = set(body.non_business_dates)
        added, removed = sorted(after - before), sorted(before - after)
        latest = latest_day(db, fund)
        horizon = latest.as_of if latest is not None else None
        for d in [*added, *removed]:
            if horizon is not None and d <= horizon:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"{d} is on or before {fund.code}'s latest loaded day, {horizon}; "
                    "the calendar can change only after it.")
        for d in added:
            if d == fund.start_date:
                raise HTTPException(status.HTTP_409_CONFLICT, f"{d} is {fund.code}'s first business day.")
            if d.weekday() >= 5:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{d} is a weekend, never a business day.")
        if added or removed:
            fund.non_business_dates = sorted(after)
            audit.append(admin.username, admin.role, "FUND_CALENDAR_CHANGED", {
                "code": fund.code, "added": [str(d) for d in added], "removed": [str(d) for d in removed],
            })
    db.commit()
    return {**fund_detail(db, fund), "ai": ai_state(fund)}
