"""Administration: each fund's AI provider, and requests to unlock a signed-off day.

``funds.ai_provider`` names the AI provider a fund's runs use when its AI is switched on
(``None``: the server's default). The switch itself stays in ``funds.settings``.

``unlock_requests`` holds the two-person unlock of a signed-off day (spec section 9): an
administrator asks with a reason, a different approver confirms within 24 hours. A request
is ``pending`` until it is ``confirmed``, ``declined`` (by an approver), ``withdrawn`` (by
its requester) or ``expired`` (24 hours passed unconfirmed). At most one pending request
per day (a partial unique index). ``rp_app`` may read, add and change requests; every step
is also in the audit log.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rp_app"


def upgrade() -> None:
    op.add_column("funds", sa.Column("ai_provider", sa.String(length=32), nullable=True))
    op.create_table(
        "unlock_requests",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("business_day_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'declined', 'withdrawn', 'expired')", name="unlock_requests_status"
        ),
        sa.ForeignKeyConstraint(["business_day_id"], ["business_days.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fund_id"], ["funds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("unlock_requests_fund_status", "unlock_requests", ["fund_id", "status"], unique=False)
    op.create_index(
        "unlock_requests_one_pending",
        "unlock_requests",
        ["business_day_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON unlock_requests TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("unlock_requests_one_pending", table_name="unlock_requests")
    op.drop_index("unlock_requests_fund_status", table_name="unlock_requests")
    op.drop_table("unlock_requests")
    op.drop_column("funds", "ai_provider")
