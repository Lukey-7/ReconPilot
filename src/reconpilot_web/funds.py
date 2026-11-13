"""Funds, their settings and their business calendar.

A fund has a start date (its first business day in ReconPilot) and a list of
non-business dates (holidays). Its business days are the weekdays from the
start date on that are not holidays. Days are worked in order: a day must be
signed off before the next business day can be uploaded or run (spec 7.5), so
``previous_business_day`` is what the upload and run routes check against.

Settings live in ``funds.settings`` (JSONB). Anything not set there falls back
to ``DEFAULT_FUND_SETTINGS``, which are the engine's own defaults, so a fund
created with no settings behaves exactly like the command line.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from reconpilot.ledger import LifecycleSettings
from reconpilot.models import BASE_CURRENCY
from reconpilot.pipeline import CHECK_SETTINGS
from reconpilot_web.auditlog import DbAuditLog
from reconpilot_web.auth import SYSTEM_ACTOR, SYSTEM_ROLE, current_user, get_db
from reconpilot_web.models import BusinessDay, Fund, User

_ENGINE_LIFECYCLE = LifecycleSettings()

DEFAULT_FUND_SETTINGS: dict[str, Any] = {
    "materiality_bp": _ENGINE_LIFECYCLE.materiality_bp,  # 1.0
    "escalate_after_days": _ENGINE_LIFECYCLE.escalate_after_days,  # 5
    "sla_days_material": _ENGINE_LIFECYCLE.sla_days_material,  # 2
    "sla_days_other": _ENGINE_LIFECYCLE.sla_days_other,  # 5
    "ai_enabled": False,
    "check_settings": {},
}

FUND_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")


# --------------------------------------------------------------------------- settings


def fund_settings(fund: Fund) -> dict[str, Any]:
    """The fund's settings with every missing key filled from ``DEFAULT_FUND_SETTINGS``."""
    stored = fund.settings or {}
    merged = {key: stored.get(key, default) for key, default in DEFAULT_FUND_SETTINGS.items()}
    merged["check_settings"] = dict(merged["check_settings"] or {})
    return merged


def fund_lifecycle(fund: Fund) -> LifecycleSettings:
    """The engine's ``LifecycleSettings`` for this fund."""
    s = fund_settings(fund)
    return LifecycleSettings(
        materiality_bp=float(s["materiality_bp"]),
        escalate_after_days=int(s["escalate_after_days"]),
        sla_days_material=int(s["sla_days_material"]),
        sla_days_other=int(s["sla_days_other"]),
    )


def fund_check_settings(fund: Fund) -> dict:
    """Keyword arguments for ``nav.run_checks`` (via ``pipeline.run_day(check_settings=...)``).

    Empty means the engine's defaults.
    """
    return dict(fund_settings(fund)["check_settings"])


def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """``settings`` merged over the defaults, or ``ValueError`` naming what is wrong."""
    unknown = sorted(set(settings) - set(DEFAULT_FUND_SETTINGS))
    if unknown:
        raise ValueError(f"Unknown fund settings: {', '.join(unknown)}.")
    merged = {**DEFAULT_FUND_SETTINGS, **settings}
    bp = merged["materiality_bp"]
    if isinstance(bp, bool) or not isinstance(bp, (int, float)) or not bp >= 0 or bp == float("inf"):
        raise ValueError("materiality_bp must be a number of basis points, 0 or more.")
    for key in ("escalate_after_days", "sla_days_material", "sla_days_other"):
        if not isinstance(merged[key], int) or isinstance(merged[key], bool) or merged[key] < 0:
            raise ValueError(f"{key} must be a whole number of business days, 0 or more.")
    if not isinstance(merged["ai_enabled"], bool):
        raise ValueError("ai_enabled must be true or false.")
    checks = merged["check_settings"]
    if not isinstance(checks, dict):
        raise ValueError("check_settings must be an object.")
    bad = sorted(set(checks) - set(CHECK_SETTINGS))
    if bad:
        raise ValueError(f"Unknown check settings: {', '.join(bad)}; allowed: {', '.join(CHECK_SETTINGS)}.")
    merged["check_settings"] = dict(checks)
    return merged


# --------------------------------------------------------------------------- calendar


def is_business_day(fund: Fund, d: date) -> bool:
    """A weekday that is not one of the fund's non-business dates."""
    return d.weekday() < 5 and d not in set(fund.non_business_dates or ())


def previous_business_day(fund: Fund, d: date) -> date | None:
    """The business day before ``d``, or ``None`` when ``d`` is the fund's first day.

    ``None`` too for any ``d`` on or before the start date, since there is no
    earlier day in ReconPilot to carry from.
    """
    if d <= fund.start_date:
        return None
    holidays = set(fund.non_business_dates or ())
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5 or prev in holidays:
        prev -= timedelta(days=1)
    return prev if prev >= fund.start_date else None


# --------------------------------------------------------------------------- creation


def normalise_code(code: str) -> str:
    return code.strip().upper()


def create_fund(
    session: Session,
    code: str,
    name: str,
    start_date: date,
    *,
    base_currency: str = BASE_CURRENCY,
    non_business_dates: Iterable[date] = (),
    settings: dict[str, Any] | None = None,
    created_by: User | None = None,
    actor: str = SYSTEM_ACTOR,
    actor_role: str = SYSTEM_ROLE,
) -> Fund:
    """Add a fund and audit ``FUND_CREATED`` in the caller's transaction.

    Raises ``ValueError`` for a malformed or taken code, an empty name, a start
    date that is not a business day, an unsupported base currency or bad settings.
    """
    code = normalise_code(code)
    if not FUND_CODE_PATTERN.match(code):
        raise ValueError("Fund code must be 1 to 32 letters, digits, '-' or '_', starting with a letter or digit.")
    name = name.strip()
    if not name or len(name) > 200 or not name.isprintable():
        raise ValueError("Fund name must be 1 to 200 printable characters.")
    base_currency = base_currency.strip().upper()
    if base_currency != BASE_CURRENCY:
        # The engine values everything in USD: fx_rates.csv gives USD per unit of each currency.
        raise ValueError(f"Base currency must be {BASE_CURRENCY}; the engine values funds in {BASE_CURRENCY}.")
    holidays = sorted(set(non_business_dates))
    if start_date.weekday() >= 5 or start_date in holidays:
        raise ValueError(f"Start date {start_date} is not a business day.")
    merged = validate_settings(settings or {})
    if session.execute(select(Fund.id).where(Fund.code == code)).first():
        raise ValueError(f"Fund {code} already exists.")
    fund = Fund(
        code=code,
        name=name,
        base_currency=base_currency,
        start_date=start_date,
        non_business_dates=holidays,
        settings=merged,
        created_by=created_by.id if created_by is not None else None,
    )
    session.add(fund)
    session.flush()
    if created_by is not None:
        actor, actor_role = created_by.username, created_by.role
    DbAuditLog(session, fund_id=fund.id).append(
        actor,
        actor_role,
        "FUND_CREATED",
        {
            "code": code,
            "name": name,
            "base_currency": base_currency,
            "start_date": str(start_date),
            "non_business_dates": [str(d) for d in holidays],
            "settings": merged,
        },
    )
    return fund


# --------------------------------------------------------------------------- lookups


def get_fund(db: Session, code: str) -> Fund:
    """The fund with this code, or 404."""
    fund = db.execute(select(Fund).where(Fund.code == normalise_code(code))).scalar_one_or_none()
    if fund is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No fund {code}.")
    return fund


def latest_day(db: Session, fund: Fund) -> BusinessDay | None:
    """The fund's most recent business day that has a row (files uploaded at least once)."""
    return db.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund.id).order_by(BusinessDay.as_of.desc()).limit(1)
    ).scalar_one_or_none()


def fund_summary(db: Session, fund: Fund) -> dict[str, Any]:
    latest = latest_day(db, fund)
    return {
        "code": fund.code,
        "name": fund.name,
        "base_currency": fund.base_currency,
        "start_date": str(fund.start_date),
        "latest_day": str(latest.as_of) if latest else None,
        "latest_status": latest.status if latest else None,
    }


def fund_detail(db: Session, fund: Fund) -> dict[str, Any]:
    return {
        **fund_summary(db, fund),
        "non_business_dates": [str(d) for d in sorted(fund.non_business_dates or ())],
        "settings": fund_settings(fund),
    }


# --------------------------------------------------------------------------- routes

router = APIRouter(prefix="/api/funds", tags=["funds"])


@router.get("")
def list_funds(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    funds = db.execute(select(Fund).order_by(Fund.code)).scalars().all()
    return [fund_summary(db, f) for f in funds]


@router.get("/{code}")
def read_fund(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return fund_detail(db, get_fund(db, code))
