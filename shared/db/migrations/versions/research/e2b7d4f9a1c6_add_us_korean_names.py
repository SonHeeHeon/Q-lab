"""add korean_name + isin to stocks_us (Korean-searchable US universe)

Revision ID: e2b7d4f9a1c6
Revises: d9e4f7a2b5c1
Create Date: 2026-07-21

The stocks_us universe only stored English names, so in-app Korean-language
search couldn't find US tickers. These nullable columns hold the Korean
display name and ISIN, backfilled from Toss's Stock Info endpoint by
backend.app.services.batch.us_names_sync. The table itself is created
out-of-band (research/scripts/download_us_universe.py), so guard on its
presence to keep fresh-DB upgrades from failing. RESEARCH branch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2b7d4f9a1c6"
down_revision = "d9e4f7a2b5c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "stocks_us" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("stocks_us")}
    if "korean_name" not in existing:
        op.add_column("stocks_us", sa.Column("korean_name", sa.Text(), nullable=True))
    if "isin" not in existing:
        op.add_column("stocks_us", sa.Column("isin", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "stocks_us" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("stocks_us")}
    with op.batch_alter_table("stocks_us", schema=None) as batch_op:
        if "isin" in existing:
            batch_op.drop_column("isin")
        if "korean_name" in existing:
            batch_op.drop_column("korean_name")
