"""Initial schema: every table, the application role and the append-only audit log.

The application connects as ``rp_app``, which may read and write every table
except ``audit_log`` (SELECT and INSERT only) and ``instance_settings`` (SELECT
only: the mode is written once, by ``reconpilot-web migrate``). A trigger also
refuses UPDATE, DELETE and TRUNCATE on ``audit_log`` for every role, superusers
included, so the trail cannot be edited through the application or by accident.

The role's password comes from ``RP_APP_DB_PASSWORD``. Only for a database on
this machine (the embedded development server) does it default to ``rp_app_dev``.

Revision ID: 0001
Revises:
Create Date: 2026-11-13 13:40:28.207020
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_cache',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('prompt_version', sa.String(length=32), server_default='', nullable=False),
    sa.Column('response', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('ts', sa.String(length=40), nullable=False),
    sa.Column('actor', sa.String(length=128), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('fund_id', sa.Integer(), nullable=True),
    sa.Column('case_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('seq')
    )
    op.create_index('audit_log_action', 'audit_log', ['action'], unique=False)
    op.create_index('audit_log_case', 'audit_log', ['case_id'], unique=False)
    op.create_index('audit_log_fund_seq', 'audit_log', ['fund_id', 'seq'], unique=False)
    op.create_table('instance_settings',
    sa.Column('id', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode IN ('real', 'demo')", name='instance_settings_mode'),
    sa.CheckConstraint('id = 1', name='instance_settings_single_row'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=128), server_default='', nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('failed_logins', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('external_subject', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('analyst', 'approver', 'viewer')", name='users_role'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_subject'),
    sa.UniqueConstraint('username')
    )
    op.create_table('funds',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('base_currency', sa.String(length=3), server_default='USD', nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('non_business_dates', postgresql.ARRAY(sa.Date()), server_default=sa.text("'{}'::date[]"), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('is_demo', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('demo_visitor', sa.String(length=128), nullable=True),
    sa.Column('demo_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('jobs',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='queued', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default=sa.text('3'), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('locked_by', sa.String(length=128), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name='jobs_status'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('jobs_claim', 'jobs', ['status', 'run_after'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('business_days',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('fund_id', sa.Integer(), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='uploaded', nullable=False),
    sa.Column('nav', sa.Float(), nullable=True),
    sa.Column('nav_per_share', sa.Float(), nullable=True),
    sa.Column('prior_nav_per_share', sa.Float(), nullable=True),
    sa.Column('nav_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('checks', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('release_ready', sa.Boolean(), nullable=True),
    sa.Column('release', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('validation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('run_by', sa.Integer(), nullable=True),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signed_off_by', sa.Integer(), nullable=True),
    sa.Column('signed_off_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('uploaded', 'validated', 'running', 'ready', 'signed_off', 'failed')", name='business_days_status'),
    sa.ForeignKeyConstraint(['fund_id'], ['funds.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['signed_off_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('fund_id', 'as_of', name='business_days_fund_as_of')
    )
    op.create_table('cases',
    sa.Column('fund_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('security_id', sa.String(length=64), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('final_category', sa.String(length=32), nullable=True),
    sa.Column('ai_category', sa.String(length=32), nullable=True),
    sa.Column('ai_flag', sa.Text(), server_default='', nullable=False),
    sa.Column('nav_impact', sa.Float(), server_default=sa.text('0'), nullable=False),
    sa.Column('nav_impact_bp', sa.Float(), server_default=sa.text('0'), nullable=False),
    sa.Column('gross_exposure', sa.Float(), server_default=sa.text('0'), nullable=False),
    sa.Column('material', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('escalated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('sla_breached', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('age_days', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('age_bucket', sa.String(length=16), server_default='0-1', nullable=False),
    sa.Column('first_seen', sa.Date(), nullable=True),
    sa.Column('last_as_of', sa.Date(), nullable=False),
    sa.Column('cleared_on', sa.Date(), nullable=True),
    sa.Column('resolved_category', sa.String(length=32), nullable=True),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fund_id'], ['funds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('fund_id', 'case_id', name='cases_pkey')
    )
    op.create_index('cases_fund_last_as_of', 'cases', ['fund_id', 'last_as_of'], unique=False)
    op.create_table('breaks',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('business_day_id', sa.Integer(), nullable=False),
    sa.Column('break_id', sa.String(length=64), nullable=False),
    sa.Column('case_id', sa.String(length=64), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('security_id', sa.String(length=64), server_default='', nullable=False),
    sa.Column('book_value', sa.Float(), nullable=True),
    sa.Column('custodian_value', sa.Float(), nullable=True),
    sa.Column('difference', sa.Float(), server_default=sa.text('0'), nullable=False),
    sa.Column('reference', sa.String(length=128), server_default='', nullable=False),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['business_day_id'], ['business_days.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('business_day_id', 'break_id', name='breaks_day_break')
    )
    op.create_index(op.f('ix_breaks_case_id'), 'breaks', ['case_id'], unique=False)
    op.create_table('case_snapshots',
    sa.Column('fund_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=64), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('business_day_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('is_open', sa.Boolean(), nullable=False),
    sa.Column('nav_impact', sa.Float(), server_default=sa.text('0'), nullable=False),
    sa.Column('material', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('escalated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('sla_breached', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('age_days', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['business_day_id'], ['business_days.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['fund_id'], ['funds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('fund_id', 'case_id', 'as_of', name='case_snapshots_pkey')
    )
    op.create_index('case_snapshots_fund_as_of', 'case_snapshots', ['fund_id', 'as_of'], unique=False)
    op.create_index(op.f('ix_case_snapshots_business_day_id'), 'case_snapshots', ['business_day_id'], unique=False)
    op.create_table('decisions',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('fund_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.String(length=64), nullable=False),
    sa.Column('business_day_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('decision', sa.String(length=16), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=True),
    sa.Column('final_category', sa.String(length=32), nullable=True),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.Column('case_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.CheckConstraint("decision IN ('approve', 'reject', 'reclassify')", name='decisions_decision'),
    sa.ForeignKeyConstraint(['business_day_id'], ['business_days.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['fund_id'], ['funds.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('decisions_fund_case', 'decisions', ['fund_id', 'case_id'], unique=False)
    op.create_index(op.f('ix_decisions_business_day_id'), 'decisions', ['business_day_id'], unique=False)
    op.create_table('input_files',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('business_day_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_day_id'], ['business_days.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('business_day_id', 'kind', name='input_files_day_kind')
    )
    op.create_table('open_items',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('business_day_id', sa.Integer(), nullable=False),
    sa.Column('side', sa.String(length=16), nullable=False),
    sa.Column('reference', sa.String(length=128), server_default='', nullable=False),
    sa.Column('security_id', sa.String(length=64), server_default='', nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('origin_date', sa.Date(), nullable=True),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("side IN ('book', 'custodian')", name='open_items_side'),
    sa.ForeignKeyConstraint(['business_day_id'], ['business_days.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_open_items_business_day_id'), 'open_items', ['business_day_id'], unique=False)
    _create_app_role()
    _grant_app_role()
    _make_audit_log_append_only()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_reject_change()")
    # The role is left in place: it may own grants in other databases on the same server.
    op.drop_index(op.f('ix_open_items_business_day_id'), table_name='open_items')
    op.drop_table('open_items')
    op.drop_table('input_files')
    op.drop_index(op.f('ix_decisions_business_day_id'), table_name='decisions')
    op.drop_index('decisions_fund_case', table_name='decisions')
    op.drop_table('decisions')
    op.drop_index(op.f('ix_case_snapshots_business_day_id'), table_name='case_snapshots')
    op.drop_index('case_snapshots_fund_as_of', table_name='case_snapshots')
    op.drop_table('case_snapshots')
    op.drop_index(op.f('ix_breaks_case_id'), table_name='breaks')
    op.drop_table('breaks')
    op.drop_index('cases_fund_last_as_of', table_name='cases')
    op.drop_table('cases')
    op.drop_table('business_days')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index('jobs_claim', table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('funds')
    op.drop_table('users')
    op.drop_table('instance_settings')
    op.drop_index('audit_log_fund_seq', table_name='audit_log')
    op.drop_index('audit_log_case', table_name='audit_log')
    op.drop_index('audit_log_action', table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_table('ai_cache')


# --------------------------------------------------------------------------- role and audit guard

APP_ROLE = "rp_app"
DEV_PASSWORD = "rp_app_dev"
_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}

# Tables the application may read and change. audit_log and instance_settings are granted separately.
APP_TABLES = (
    "users",
    "sessions",
    "funds",
    "business_days",
    "input_files",
    "cases",
    "case_snapshots",
    "breaks",
    "open_items",
    "decisions",
    "jobs",
    "ai_cache",
)


def _app_password() -> str:
    config = op.get_context().config
    password = (config.attributes.get("app_db_password") if config is not None else None) or os.environ.get(
        "RP_APP_DB_PASSWORD", ""
    )
    if password:
        return password
    host = op.get_bind().engine.url.host or ""
    if host in _LOCAL_HOSTS:
        return DEV_PASSWORD
    raise RuntimeError("set RP_APP_DB_PASSWORD: the rp_app role needs a password on a non-local database")


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _create_app_role() -> None:
    password = _literal(_app_password())
    op.execute(
        f"""
        DO $rp$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD {password};
            END IF;
        END
        $rp$
        """
    )


def _grant_app_role() -> None:
    op.execute(f"GRANT CONNECT ON DATABASE {_current_database()} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(APP_TABLES)} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON instance_settings, alembic_version TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def _current_database() -> str:
    name = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    return '"' + name.replace('"', '""') + '"'


def _make_audit_log_append_only() -> None:
    op.execute(
        """
        CREATE FUNCTION audit_log_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $rp$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $rp$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION audit_log_reject_change()
        """
    )
