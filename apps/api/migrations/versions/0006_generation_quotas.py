"""Add opt-in persistent demo generation allowances."""

from alembic import op
import sqlalchemy as sa

revision = "0006_generation_quotas"
down_revision = "0005_workflow_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_quotas",
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("generation_limit", sa.Integer(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.CheckConstraint("generation_limit >= 0", name="ck_generation_quota_limit"),
        sa.CheckConstraint("used >= 0 AND used <= generation_limit", name="ck_generation_quota_used"),
    )


def downgrade() -> None:
    op.drop_table("generation_quotas")
