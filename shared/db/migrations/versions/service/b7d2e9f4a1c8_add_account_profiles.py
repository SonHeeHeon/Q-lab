"""add account_profiles

Revision ID: b7d2e9f4a1c8
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "b7d2e9f4a1c8"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_profiles",
        sa.Column("account_key", sa.Text(), primary_key=True),
        sa.Column("broker", sa.Text(), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=True),
        sa.Column("profile_type", sa.Text(), nullable=False),
        sa.Column(
            "quant_enabled", sa.Boolean(), nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("sleeves_json", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("account_profiles")
