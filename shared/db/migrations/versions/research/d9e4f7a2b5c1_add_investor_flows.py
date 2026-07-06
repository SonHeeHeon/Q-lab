"""add investor_flows_daily table (투자자별 순매수 거래대금)

Revision ID: d9e4f7a2b5c1
Revises: c8d2f6a1b4e3
Create Date: 2026-07-07

Daily net-purchase trading value by investor type (foreign/institution/
individual), KRW, positive = net buying. Data source: pykrx
update_investor_flows. Feeds the Flow factor group (FOREIGN_NET_20D etc.)
of the composite scoring equation. RESEARCH branch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d9e4f7a2b5c1"
down_revision = "c8d2f6a1b4e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investor_flows_daily",
        sa.Column("stock_code", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("foreign_net", sa.Numeric(), nullable=True),
        sa.Column("inst_net", sa.Numeric(), nullable=True),
        sa.Column("indiv_net", sa.Numeric(), nullable=True),
        sa.PrimaryKeyConstraint("stock_code", "date"),
    )
    with op.batch_alter_table("investor_flows_daily", schema=None) as batch_op:
        batch_op.create_index("idx_investor_flows_date", ["date"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("investor_flows_daily", schema=None) as batch_op:
        batch_op.drop_index("idx_investor_flows_date")
    op.drop_table("investor_flows_daily")
