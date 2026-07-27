"""add trades.broker + make trades.account_type nullable

Revision ID: 1a2b3c4d5e6f
Revises: 0e1573ebfd65
Create Date: 2026-07-27

Toss fills were being persisted with account_type falling back to
AccountType.PAPER, colliding with the KIS 모의(paper) account. This adds a
``broker`` column (server_default 'KIS' — every existing tracked trade to
date is KIS) so Toss trades are tagged broker='TOSS', and relaxes
``account_type`` to nullable so a Toss trade (which has no KIS
PAPER/REAL/ISA identity) can be stored as account_type=NULL instead of being
mislabeled PAPER.

This is pure DDL: pre-existing Toss trade rows (already stored with
account_type='PAPER' before this migration) are NOT backfilled to
broker='TOSS'/account_type=NULL here — they keep their default broker='KIS'
value. A future data-fix migration or backfill script could reconstruct the
correct broker from each row's raw_order JSON (which already carries
"broker": "TOSS"/"KIS") if that history needs correcting.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "1a2b3c4d5e6f"
down_revision = "0e1573ebfd65"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "broker", sa.Text(), server_default=sa.text("'KIS'"), nullable=False
            )
        )
        batch_op.alter_column(
            "account_type",
            existing_type=sa.Text(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.alter_column(
            "account_type",
            existing_type=sa.Text(),
            nullable=False,
        )
        batch_op.drop_column("broker")
