"""add stock_ratings/position_ratings/rating_batch_runs tables (매수/매도 평가)

Revision ID: 0e1573ebfd65
Revises: a4b8c2d6e0f1
Create Date: 2026-07-24

매수축(stock_ratings, 종목당 1행) / 매도축(position_ratings, 계좌×종목당
1행) 현재-상태 테이블과 일일 평가 배치 갱신 이력(rating_batch_runs)을
추가한다. SERVICE branch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0e1573ebfd65"
down_revision = "a4b8c2d6e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_ratings",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("buy_grade", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("percentile", sa.Float(), nullable=True),
        sa.Column("weakest_group", sa.Text(), nullable=True),
        sa.Column("strategy_name", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "position_ratings",
        sa.Column("broker", sa.Text(), nullable=False),
        sa.Column("account_key", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("sell_grade", sa.Text(), nullable=False),
        sa.Column("reason_json", sa.Text(), nullable=False),
        sa.Column("pl_rate", sa.Float(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("broker", "account_key", "code"),
    )
    op.create_table(
        "rating_batch_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("universe_size", sa.Integer(), nullable=True),
        sa.Column("stored_count", sa.Integer(), nullable=True),
        sa.Column(
            "error_count", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    op.drop_table("rating_batch_runs")
    op.drop_table("position_ratings")
    op.drop_table("stock_ratings")
