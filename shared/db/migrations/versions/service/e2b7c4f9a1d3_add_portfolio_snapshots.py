"""add portfolio_snapshots table

Revision ID: e2b7c4f9a1d3
Revises: d6c9e4a5b7f1
Create Date: 2026-07-06

Daily portfolio NAV per account for the performance-tracking feature
(paper/real equity curves). SERVICE branch (live app state).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2b7c4f9a1d3"
down_revision = "d6c9e4a5b7f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshots",
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(), nullable=False),
        sa.Column(
            "cash", sa.Numeric(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "holdings_value",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'BROKER'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("account_type", "date"),
    )
    with op.batch_alter_table("portfolio_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            "idx_snapshots_account_date",
            ["account_type", "date"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("portfolio_snapshots", schema=None) as batch_op:
        batch_op.drop_index("idx_snapshots_account_date")
    op.drop_table("portfolio_snapshots")
