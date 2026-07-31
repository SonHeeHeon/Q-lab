"""add rebalance_targets

Revision ID: c8e3f0a5b2d9
Revises: b7d2e9f4a1c8
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "c8e3f0a5b2d9"
down_revision = "b7d2e9f4a1c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rebalance_targets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.Column("strategy_name", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("target_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("account_type", "strategy_name", "period"),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    op.drop_table("rebalance_targets")
