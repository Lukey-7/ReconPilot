"""Each user's preferred fund: the fund they last chose in the fund selector.

A nullable key to ``funds`` that is cleared when the fund is removed. ``rp_app``
already has UPDATE on ``users``, which covers the new column.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_fund_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "users_preferred_fund_id_fkey", "users", "funds", ["preferred_fund_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("users_preferred_fund_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "preferred_fund_id")
