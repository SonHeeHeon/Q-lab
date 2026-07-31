"""order_proposals: PROPOSED 상태 부분 유니크 인덱스

Revision ID: f7a3d8c2e9b5
Revises: e5b2c9d7f4a1
Create Date: 2026-08-01

동일 (계좌, 전략, 종목, 방향, 마켓)의 PROPOSED 중복을 DB 차원에서 차단 —
앱 레벨 dedup(check-then-insert)의 경합 창을 막는 이중 방어 (리뷰 P0-3).
"""
from alembic import op

revision = "f7a3d8c2e9b5"
down_revision = "e5b2c9d7f4a1"
branch_labels = None
depends_on = None

_INDEX = "uq_order_proposals_proposed"


def upgrade() -> None:
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX} ON order_proposals"
        " (account_type, strategy_name, stock_code, side, market)"
        " WHERE status = 'PROPOSED'"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
