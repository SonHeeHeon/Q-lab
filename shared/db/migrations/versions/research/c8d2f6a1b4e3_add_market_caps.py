"""add market_caps table (true daily market capitalization)

Revision ID: c8d2f6a1b4e3
Revises: bc1fc0ca2a36
Create Date: 2026-07-07

The engine's MARKET_CAP factor/filter previously fell back to a close×volume
turnover proxy, which silently turned "market cap >= 100B" filters into
"top-turnover-of-the-day" filters. MARKET_CAP now reads this table only.
Populate via research.data_ingestion.pykrx_loader.update_market_caps.
RESEARCH branch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8d2f6a1b4e3"
down_revision = "bc1fc0ca2a36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_caps",
        sa.Column("stock_code", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("market_cap", sa.Numeric(), nullable=False),
        sa.Column("shares_outstanding", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("stock_code", "date"),
    )
    with op.batch_alter_table("market_caps", schema=None) as batch_op:
        batch_op.create_index("idx_market_caps_date", ["date"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("market_caps", schema=None) as batch_op:
        batch_op.drop_index("idx_market_caps_date")
    op.drop_table("market_caps")
