"""Demo visitors (spec section 11): each one-click demo user belongs to one visitor's fund.

``users.demo_fund_id`` names the demo fund a sandbox user was made for. Such a user sees
that fund only, and goes with it: deleting an expired visitor fund deletes its users (and,
through them, their sessions). Real users have no demo fund. ``funds.demo_resume_hash`` is
the SHA-256 of the token in the visitor's ``rp_demo`` cookie, which lets them return to
their fund after their session has ended. ``funds_demo_expiry`` serves the cleanup job,
which looks for demo funds past their expiry. ``rp_app`` already has
UPDATE and DELETE on ``users`` and ``funds``, which covers both.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("demo_fund_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "users_demo_fund_id_fkey", "users", "funds", ["demo_fund_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_users_demo_fund_id", "users", ["demo_fund_id"], unique=False)
    op.add_column("funds", sa.Column("demo_resume_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_funds_demo_resume_hash", "funds", ["demo_resume_hash"], unique=True)
    op.create_index("funds_demo_expiry", "funds", ["is_demo", "demo_expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("funds_demo_expiry", table_name="funds")
    op.drop_index("ix_funds_demo_resume_hash", table_name="funds")
    op.drop_column("funds", "demo_resume_hash")
    op.drop_index("ix_users_demo_fund_id", table_name="users")
    op.drop_constraint("users_demo_fund_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "demo_fund_id")
