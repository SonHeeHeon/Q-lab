"""default auto ramp — 미설정(0) 계좌를 자동(-1)으로

Revision ID: e5b2c9d7f4a1
Revises: d4f1a7c3e8b0
Create Date: 2026-08-01

ramp study(2026-07-31) 결정표를 라이브에 기본 적용: ramp_in_months=-1(자동)이
퀀트 ON 시점 국면×슬리브로 분할/올인을 스스로 결정한다. 사용자가 화면에서
0(안 함)·3/6/12(수동)로 되돌릴 수 있다.
"""
from alembic import op

revision = "e5b2c9d7f4a1"
down_revision = "d4f1a7c3e8b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE account_profiles SET ramp_in_months = -1 WHERE ramp_in_months = 0"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE account_profiles SET ramp_in_months = 0 WHERE ramp_in_months = -1"
    )
