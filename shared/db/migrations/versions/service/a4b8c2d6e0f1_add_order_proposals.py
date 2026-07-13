"""add order_proposals table (승인형 반자동 제안)

Revision ID: a4b8c2d6e0f1
Revises: f3a1b2c4d5e6
Create Date: 2026-07-13

Daily strategy-vs-holdings diff proposals; user approval mints a
client_order_id and executes through the order safety gateway.
SERVICE branch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a4b8c2d6e0f1"
down_revision = "f3a1b2c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("proposal_date", sa.Date(), nullable=False),
        sa.Column(
            "account_type", sa.Text(), nullable=False,
            server_default=sa.text("'PAPER'"),
        ),
        sa.Column("strategy_name", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=True),
        sa.Column("stock_code", sa.Text(), nullable=False),
        sa.Column(
            "market", sa.Text(), nullable=False, server_default=sa.text("'KR'")
        ),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column(
            "order_type", sa.Text(), nullable=False,
            server_default=sa.text("'LIMIT'"),
        ),
        sa.Column("limit_price", sa.Numeric(), nullable=True),
        sa.Column("last_price", sa.Numeric(), nullable=True),
        sa.Column("estimated_notional", sa.Numeric(), nullable=True),
        sa.Column("reason_json", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False,
            server_default=sa.text("'PROPOSED'"),
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("client_order_id", sa.Text(), nullable=True),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"]),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    with op.batch_alter_table("order_proposals", schema=None) as batch_op:
        batch_op.create_index(
            "idx_proposals_status_date", ["status", "proposal_date"], unique=False
        )
        batch_op.create_index("idx_proposals_batch", ["batch_id"], unique=False)
        batch_op.create_index(
            "idx_proposals_client_order_id", ["client_order_id"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("order_proposals", schema=None) as batch_op:
        batch_op.drop_index("idx_proposals_client_order_id")
        batch_op.drop_index("idx_proposals_batch")
        batch_op.drop_index("idx_proposals_status_date")
    op.drop_table("order_proposals")
