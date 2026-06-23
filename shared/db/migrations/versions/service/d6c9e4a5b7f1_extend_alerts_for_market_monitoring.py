"""extend alerts for market monitoring

Revision ID: d6c9e4a5b7f1
Revises: b1f4a2d9c6e7
Create Date: 2026-06-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d6c9e4a5b7f1"
down_revision = "b1f4a2d9c6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "broker",
                sa.Text(),
                server_default=sa.text("'KIS'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "market_country",
                sa.Text(),
                server_default=sa.text("'KR'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("symbol", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "action",
                sa.Text(),
                server_default=sa.text("'NOTIFY'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("order_quantity", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("account_type", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("account_id", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_enabled",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("last_checked_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.create_index("idx_alerts_enabled", ["is_enabled", "triggered_at"], unique=False)
        batch_op.create_index("idx_alerts_market_symbol", ["market_country", "symbol"], unique=False)

    op.execute("UPDATE alerts SET symbol = stock_code WHERE symbol IS NULL OR symbol = ''")


def downgrade() -> None:
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_index("idx_alerts_market_symbol")
        batch_op.drop_index("idx_alerts_enabled")
        batch_op.drop_column("last_error")
        batch_op.drop_column("last_price")
        batch_op.drop_column("last_checked_at")
        batch_op.drop_column("is_enabled")
        batch_op.drop_column("account_id")
        batch_op.drop_column("account_type")
        batch_op.drop_column("order_quantity")
        batch_op.drop_column("action")
        batch_op.drop_column("symbol")
        batch_op.drop_column("market_country")
        batch_op.drop_column("broker")
