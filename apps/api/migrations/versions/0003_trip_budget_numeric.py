"""Store trip budgets as fixed-point numeric values."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_trip_budget_numeric"
down_revision = "0002_job_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trips") as batch_op:
        batch_op.alter_column(
            "budget",
            existing_type=sa.Float(),
            type_=sa.Numeric(14, 2),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("trips") as batch_op:
        batch_op.alter_column(
            "budget",
            existing_type=sa.Numeric(14, 2),
            type_=sa.Float(),
            existing_nullable=False,
        )
