"""phase6 order tracking journal ai

Revision ID: b1f4a2d9c6e7
Revises: 88ea31070844
Create Date: 2026-06-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1f4a2d9c6e7"
down_revision = "88ea31070844"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.Text(),
                server_default=sa.text("'PENDING'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("submitted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "filled_quantity",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("filled_price", sa.Numeric(), nullable=True))
        batch_op.add_column(
            sa.Column("fees", sa.Numeric(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.add_column(
            sa.Column("taxes", sa.Numeric(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.add_column(sa.Column("filled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("canceled_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_checked_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("raw_order", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("raw_execution", sa.Text(), nullable=True))
        batch_op.create_index("idx_trades_order_no", ["kis_order_no"], unique=False)
        batch_op.create_index(
            "idx_trades_status_checked",
            ["status", "last_checked_at"],
            unique=False,
        )

    with op.batch_alter_table("trade_journal", schema=None) as batch_op:
        batch_op.add_column(sa.Column("llm_analysis_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("llm_violation_tags", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("llm_analyzed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("llm_analysis_model", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trade_journal", schema=None) as batch_op:
        batch_op.drop_column("llm_analysis_model")
        batch_op.drop_column("llm_analyzed_at")
        batch_op.drop_column("llm_violation_tags")
        batch_op.drop_column("llm_analysis_summary")

    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_index("idx_trades_status_checked")
        batch_op.drop_index("idx_trades_order_no")
        batch_op.drop_column("raw_execution")
        batch_op.drop_column("raw_order")
        batch_op.drop_column("last_checked_at")
        batch_op.drop_column("canceled_at")
        batch_op.drop_column("filled_at")
        batch_op.drop_column("taxes")
        batch_op.drop_column("fees")
        batch_op.drop_column("filled_price")
        batch_op.drop_column("filled_quantity")
        batch_op.drop_column("submitted_at")
        batch_op.drop_column("status")
