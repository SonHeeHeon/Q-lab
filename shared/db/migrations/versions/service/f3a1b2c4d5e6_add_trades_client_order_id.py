"""add trades.client_order_id for idempotency

Revision ID: f3a1b2c4d5e6
Revises: e2b7c4f9a1d3
Create Date: 2026-07-06

Idempotency key so a retried order submission with the same client_order_id is
deduplicated instead of placing a second real order (P1-2). Unique index
allows multiple NULLs (orders without a key are unaffected).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a1b2c4d5e6"
down_revision = "e2b7c4f9a1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.add_column(sa.Column("client_order_id", sa.Text(), nullable=True))
        batch_op.create_index(
            "idx_trades_client_order_id",
            ["client_order_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_index("idx_trades_client_order_id")
        batch_op.drop_column("client_order_id")
