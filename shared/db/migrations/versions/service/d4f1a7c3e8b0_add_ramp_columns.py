"""add ramp columns to account_profiles

Revision ID: d4f1a7c3e8b0
Revises: c8e3f0a5b2d9
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f1a7c3e8b0"
down_revision = "c8e3f0a5b2d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("quant_enabled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "ramp_in_months", sa.Integer(), nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("account_profiles", schema=None) as batch_op:
        batch_op.drop_column("ramp_in_months")
        batch_op.drop_column("quant_enabled_at")
