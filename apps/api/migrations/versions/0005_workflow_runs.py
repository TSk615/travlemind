"""Add durable workflow runs and job associations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_workflow_runs"
down_revision = "0004_search_role_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("trip_id", sa.String(32), sa.ForeignKey("trips.id"), nullable=False),
        sa.Column("original_job_id", sa.String(40), nullable=False),
        sa.Column("current_job_id", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("graph_version", sa.String(64), nullable=False),
        sa.Column("state_schema_version", sa.Integer(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=True),
        sa.Column("expected_trip_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("failed_node", sa.String(64), nullable=True),
        sa.Column("committed_job_id", sa.String(40), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_runs_owner_trip", "workflow_runs", ["owner_user_id", "trip_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status", "updated_at"])
    with op.batch_alter_table("job_records") as batch_op:
        batch_op.add_column(sa.Column("workflow_run_id", sa.String(40), nullable=True))
        batch_op.create_foreign_key(
            "fk_job_records_workflow_run_id",
            "workflow_runs",
            ["workflow_run_id"],
            ["id"],
        )
        batch_op.create_index("ix_job_records_workflow_run_id", ["workflow_run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job_records") as batch_op:
        batch_op.drop_index("ix_job_records_workflow_run_id")
        batch_op.drop_constraint("fk_job_records_workflow_run_id", type_="foreignkey")
        batch_op.drop_column("workflow_run_id")
    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_owner_trip", table_name="workflow_runs")
    op.drop_table("workflow_runs")
