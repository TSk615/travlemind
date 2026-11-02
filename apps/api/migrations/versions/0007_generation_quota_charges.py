"""Track job debits and idempotent terminal-failure refunds."""
from alembic import op
import sqlalchemy as sa

revision = "0007_generation_quota_charges"
down_revision = "0006_generation_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_quota_charges",
        sa.Column("job_id", sa.String(32), sa.ForeignKey("job_records.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_generation_quota_charges_user_id", "generation_quota_charges", ["user_id"])


def downgrade() -> None:
    op.drop_table("generation_quota_charges")
