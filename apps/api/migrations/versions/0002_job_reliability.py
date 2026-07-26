"""Add durable job idempotency, attempts, locks, and heartbeats."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_job_reliability"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("job_records")}
    additions = [
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True)),
    ]
    for column in additions:
        if column.name not in columns:
            op.add_column("job_records", column)

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("job_records")}
    if "ix_job_records_idempotency" not in indexes:
        op.create_index(
            "ix_job_records_idempotency",
            "job_records",
            ["owner_user_id", "type", "idempotency_key"],
            unique=True,
        )
    if "ix_job_records_recovery" not in indexes:
        op.create_index(
            "ix_job_records_recovery",
            "job_records",
            ["status", "heartbeat_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_job_records_recovery", table_name="job_records")
    op.drop_index("ix_job_records_idempotency", table_name="job_records")
    for column_name in ("available_at", "heartbeat_at", "locked_at", "max_attempts", "attempt_count", "idempotency_key"):
        op.drop_column("job_records", column_name)
