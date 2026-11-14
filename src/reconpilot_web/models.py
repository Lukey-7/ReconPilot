"""Database tables (spec section 6).

The current state of each case is held as columns for queries plus the engine's
full ``Case`` as JSONB (``storage.case_to_dict``). Figures the engine produces as
floats are stored as double precision so results match the command line exactly.

The schema itself is created by the Alembic migrations in ``migrations/``; these
models describe the same tables and a test checks the two agree.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from reconpilot_web.db import Base

ROLES = ("analyst", "approver", "viewer")
DAY_STATUSES = ("uploaded", "validated", "running", "ready", "signed_off", "failed")
JOB_STATUSES = ("queued", "running", "done", "failed")
DECISIONS = ("approve", "reject", "reclassify")
OPEN_ITEM_SIDES = ("book", "custodian")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _now():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# --------------------------------------------------------------------------- instance


class InstanceSettings(Base):
    """One row: whether this database holds real or demo data. Written once by ``migrate``."""

    __tablename__ = "instance_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="instance_settings_single_row"),
        CheckConstraint("mode IN ('real', 'demo')", name="instance_settings_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default=text("1"))
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = _now()


def get_instance_mode(session: Session) -> str | None:
    return session.execute(select(InstanceSettings.mode).where(InstanceSettings.id == 1)).scalar_one_or_none()


def assert_instance_mode(session: Session, expected: str) -> None:
    """Refuse to run against a database written for the other mode (or never initialised)."""
    mode = get_instance_mode(session)
    if mode is None:
        raise RuntimeError("database has no instance mode; run `reconpilot-web migrate` first")
    if mode != expected:
        raise RuntimeError(f"database is a {mode} database; this instance runs in {expected} mode")


def ensure_instance_mode(session: Session, mode: str) -> None:
    """Write the instance mode if the database has none yet, then check it matches ``mode``."""
    session.execute(
        text("INSERT INTO instance_settings (id, mode) VALUES (1, :mode) ON CONFLICT (id) DO NOTHING"),
        {"mode": mode},
    )
    assert_instance_mode(session, mode)


# --------------------------------------------------------------------------- people


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="users_role"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # For single sign-on later: the identity provider's subject for this user.
    external_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = _now()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The fund the user last chose to work (see ``preferences``); cleared if the fund is removed.
    # ``use_alter``: funds.created_by points back at users, so this key is added after both tables.
    preferred_fund_id: Mapped[int | None] = mapped_column(
        ForeignKey("funds.id", ondelete="SET NULL", use_alter=True, name="users_preferred_fund_id_fkey")
    )
    # Demo mode only: the visitor fund a one-click sandbox user belongs to. Such a user sees that
    # fund alone and is deleted with it. ``None`` for every real user.
    demo_fund_id: Mapped[int | None] = mapped_column(
        ForeignKey("funds.id", ondelete="CASCADE", use_alter=True, name="users_demo_fund_id_fkey"), index=True
    )


class UserSession(Base):
    """A signed-in browser session. Only the SHA-256 of the session token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


# --------------------------------------------------------------------------- funds and days


class Fund(Base):
    __tablename__ = "funds"
    __table_args__ = (Index("funds_demo_expiry", "is_demo", "demo_expires_at"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    non_business_dates: Mapped[list[date]] = mapped_column(
        ARRAY(Date), nullable=False, server_default=text("'{}'::date[]")
    )
    # materiality_bp, escalate_after_days, sla_days_material, sla_days_other, ai_enabled, check_settings
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    demo_visitor: Mapped[str | None] = mapped_column(String(128))
    demo_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SHA-256 of the token in the visitor's ``rp_demo`` cookie, so they can return to their fund.
    demo_resume_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()


class BusinessDay(Base):
    __tablename__ = "business_days"
    __table_args__ = (
        UniqueConstraint("fund_id", "as_of", name="business_days_fund_as_of"),
        CheckConstraint(_in("status", DAY_STATUSES), name="business_days_status"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="uploaded")
    # NAV figures (engine NavResult); the full result is kept in nav_detail.
    nav: Mapped[float | None] = mapped_column(Float)
    nav_per_share: Mapped[float | None] = mapped_column(Float)
    prior_nav_per_share: Mapped[float | None] = mapped_column(Float)
    nav_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    checks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    release_ready: Mapped[bool | None] = mapped_column(Boolean)
    release: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    run_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_off_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InputFile(Base):
    """One uploaded file for a day, kept byte for byte with its SHA-256."""

    __tablename__ = "input_files"
    __table_args__ = (UniqueConstraint("business_day_id", "kind", name="input_files_day_kind"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    business_day_id: Mapped[int] = mapped_column(
        ForeignKey("business_days.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = _now()


# --------------------------------------------------------------------------- cases and evidence


class CaseRow(Base):
    """A case's current state. ``version`` increases on every change (stale-decision guard)."""

    __tablename__ = "cases"
    __table_args__ = (
        PrimaryKeyConstraint("fund_id", "case_id", name="cases_pkey"),
        Index("cases_fund_last_as_of", "fund_id", "last_as_of"),
    )

    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    security_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    final_category: Mapped[str | None] = mapped_column(String(32))
    ai_category: Mapped[str | None] = mapped_column(String(32))
    ai_flag: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    nav_impact: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    nav_impact_bp: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    gross_exposure: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    material: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sla_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    age_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    age_bucket: Mapped[str] = mapped_column(String(16), nullable=False, server_default="0-1")
    first_seen: Mapped[date | None] = mapped_column(Date)
    last_as_of: Mapped[date] = mapped_column(Date, nullable=False)  # the latest day the case was in a run
    cleared_on: Mapped[date | None] = mapped_column(Date)
    resolved_category: Mapped[str | None] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # storage.case_to_dict
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CaseSnapshot(Base):
    """A case as it stood at the end of one day (the engine's daily ledger)."""

    __tablename__ = "case_snapshots"
    __table_args__ = (
        PrimaryKeyConstraint("fund_id", "case_id", "as_of", name="case_snapshots_pkey"),
        Index("case_snapshots_fund_as_of", "fund_id", "as_of"),
    )

    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    business_day_id: Mapped[int] = mapped_column(
        ForeignKey("business_days.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)  # False when cleared that day
    nav_impact: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    material: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sla_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    age_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class BreakRow(Base):
    """One break found by a run: the evidence behind a case."""

    __tablename__ = "breaks"
    __table_args__ = (UniqueConstraint("business_day_id", "break_id", name="breaks_day_break"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    business_day_id: Mapped[int] = mapped_column(
        ForeignKey("business_days.id", ondelete="CASCADE"), nullable=False
    )
    break_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[str | None] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    security_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    book_value: Mapped[float | None] = mapped_column(Float)
    custodian_value: Mapped[float | None] = mapped_column(Float)
    difference: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    reference: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")


class OpenItem(Base):
    """A cash item left unmatched at the end of a day, carried into the next day's matching."""

    __tablename__ = "open_items"
    __table_args__ = (CheckConstraint(_in("side", OPEN_ITEM_SIDES), name="open_items_side"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    business_day_id: Mapped[int] = mapped_column(
        ForeignKey("business_days.id", ondelete="CASCADE"), nullable=False, index=True
    )
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    reference: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    security_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    origin_date: Mapped[date | None] = mapped_column(Date)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # the full item, with its trade


class Decision(Base):
    """A human decision on a case. Voided (never deleted) when a re-run makes it no longer apply."""

    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(_in("decision", DECISIONS), name="decisions_decision"),
        Index("decisions_fund_case", "fund_id", "case_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    business_day_id: Mapped[int] = mapped_column(
        ForeignKey("business_days.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))  # the case's category when decided
    final_category: Mapped[str | None] = mapped_column(String(32))  # for reclassify
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _now()
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- audit, jobs, cache


class AuditEntry(Base):
    """The hash-chained audit log (spec section 8). Append-only: see the migration's trigger.

    ``ts``, ``actor``, ``role``, ``action``, ``payload``, ``prev_hash`` and ``seq`` are the
    engine's record fields; ``hash`` is ``audit.record_hash`` of them. ``fund_id`` and
    ``case_id`` are copies for filtering and are not part of the hash. ``fund_id`` has no
    foreign key so a fund can be removed without touching its history.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("audit_log_fund_seq", "fund_id", "seq"),
        Index("audit_log_action", "action"),
        Index("audit_log_case", "case_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    ts: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fund_id: Mapped[int | None] = mapped_column(Integer)
    case_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="jobs_status"),
        Index("jobs_claim", "status", "run_after"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    run_after: Mapped[datetime] = _now()
    locked_by: Mapped[str | None] = mapped_column(String(128))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AICacheEntry(Base):
    """AI responses keyed by prompt hash (the engine's ``ResponseCache`` in the database)."""

    __tablename__ = "ai_cache"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()
