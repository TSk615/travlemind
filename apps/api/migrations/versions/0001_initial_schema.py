"""Establish the TravelMind schema and absorb legacy SQLite databases."""

from __future__ import annotations

from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


metadata = sa.MetaData()

sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("avatar", sa.String(512)),
    sa.Column("locale", sa.String(16)),
    sa.Column("password_hash", sa.String(255), nullable=False),
    sa.Column("llm_base_url", sa.String(512)),
    sa.Column("llm_api_key", sa.Text()),
    sa.Column("llm_model", sa.String(255)),
    sa.Column("llm_wire_api", sa.String(64)),
    sa.Column("llm_provider_protocol", sa.String(64)),
    sa.Column("llm_agent_provider", sa.String(64)),
    sa.Column("poi_llm_base_url", sa.String(512)),
    sa.Column("poi_llm_api_key", sa.Text()),
    sa.Column("poi_llm_model", sa.String(255)),
    sa.Column("poi_llm_wire_api", sa.String(64)),
    sa.Column("poi_llm_provider_protocol", sa.String(64)),
    sa.Column("image_base_url", sa.String(512)),
    sa.Column("image_api_key", sa.Text()),
    sa.Column("image_model", sa.String(255)),
    sa.Column("image_provider", sa.String(64)),
    sa.Column("search_service_provider", sa.String(64)),
    sa.Column("search_service_transport", sa.String(32)),
    sa.Column("search_service_base_url", sa.String(512)),
    sa.Column("search_service_api_key", sa.Text()),
    sa.Column("search_service_timeout_seconds", sa.Float(), nullable=False, server_default=sa.text("30")),
    sa.Column("xhs_source_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("disabled_at", sa.DateTime(timezone=True)),
    sa.Column("disabled_reason", sa.Text()),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

sa.Table(
    "xhs_account_sessions",
    metadata,
    sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), primary_key=True),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("xhs_user_id", sa.String(128)),
    sa.Column("display_name", sa.String(255)),
    sa.Column("session_ciphertext", sa.Text()),
    sa.Column("session_expires_at", sa.DateTime(timezone=True)),
    sa.Column("last_bound_at", sa.DateTime(timezone=True)),
    sa.Column("last_available_at", sa.DateTime(timezone=True)),
    sa.Column("last_error", sa.Text()),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

sa.Table(
    "xhs_binding_attempts",
    metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("verification_url", sa.String(1024)),
    sa.Column("verification_code", sa.String(255)),
    sa.Column("qr_image_data_url", sa.Text()),
    sa.Column("error_message", sa.Text()),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

sa.Table(
    "refresh_sessions",
    metadata,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

sa.Table(
    "trips",
    metadata,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("title", sa.String(255), nullable=False),
    sa.Column("origin", sa.String(255), nullable=False, server_default=""),
    sa.Column("destination", sa.String(255), nullable=False),
    sa.Column("start_date", sa.Date(), nullable=False),
    sa.Column("end_date", sa.Date(), nullable=False),
    sa.Column("budget", sa.Float(), nullable=False),
    sa.Column("travelers", sa.Integer(), nullable=False),
    sa.Column("interests", sa.JSON()),
    sa.Column("accommodation_preference", sa.Text()),
    sa.Column("pace", sa.String(32)),
    sa.Column("transport_mode", sa.String(32)),
    sa.Column("itinerary_json", sa.JSON()),
    sa.Column("latest_agent_trace_json", sa.JSON()),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

sa.Table(
    "trip_refine_sessions",
    metadata,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("trip_id", sa.String(32), sa.ForeignKey("trips.id"), nullable=False, unique=True, index=True),
    sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("messages_json", sa.JSON(), nullable=False),
    sa.Column("uploaded_guides_json", sa.JSON(), nullable=False),
    sa.Column("community_sources_json", sa.JSON(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

sa.Table(
    "community_posts",
    metadata,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("trip_id", sa.String(32), sa.ForeignKey("trips.id"), nullable=False, unique=True, index=True),
    sa.Column("author_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("title", sa.String(255), nullable=False),
    sa.Column("destination", sa.String(255), nullable=False),
    sa.Column("share_note", sa.Text(), nullable=False),
    sa.Column("cover_image_url", sa.String(2048)),
    sa.Column("snapshot_json", sa.JSON(), nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("source_trip_updated_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "job_records",
    metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("type", sa.String(64), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("owner_user_id", sa.String(32), index=True),
    sa.Column("trip_id", sa.String(32), sa.ForeignKey("trips.id"), index=True),
    sa.Column("payload_json", sa.JSON(), nullable=False),
    sa.Column("result_json", sa.JSON()),
    sa.Column("error_message", sa.Text()),
    sa.Column("stage", sa.String(64)),
    sa.Column("stage_message", sa.Text()),
    sa.Column("progress_percent", sa.Integer()),
    sa.Column("timeline_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
)

sa.Table(
    "image_generations",
    metadata,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("title", sa.String(255), nullable=False),
    sa.Column("destination", sa.String(255), nullable=False),
    sa.Column("scene_prompt", sa.Text(), nullable=False),
    sa.Column("mode", sa.String(32), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("visibility", sa.String(32), nullable=False),
    sa.Column("prompt", sa.Text(), nullable=False),
    sa.Column("optimized_prompt", sa.Text()),
    sa.Column("negative_prompt", sa.Text()),
    sa.Column("style_tags_json", sa.JSON(), nullable=False),
    sa.Column("source_images_json", sa.JSON(), nullable=False),
    sa.Column("reference_images_json", sa.JSON(), nullable=False),
    sa.Column("result_images_json", sa.JSON(), nullable=False),
    sa.Column("provider", sa.String(64)),
    sa.Column("model", sa.String(255)),
    sa.Column("remix_from_id", sa.String(32), sa.ForeignKey("image_generations.id"), index=True),
    sa.Column("remix_count", sa.Integer(), nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

sa.Table(
    "admin_audit_logs",
    metadata,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("admin_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("admin_email_snapshot", sa.String(255), nullable=False),
    sa.Column("action", sa.String(64), nullable=False, index=True),
    sa.Column("target_type", sa.String(64), nullable=False, index=True),
    sa.Column("target_id", sa.String(64), nullable=False, index=True),
    sa.Column("reason", sa.Text(), nullable=False),
    sa.Column("details_json", sa.JSON(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


def _add_missing_columns(table_name: str, columns: Iterable[sa.Column]) -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind, checkfirst=True)
    tables = set(sa.inspect(bind).get_table_names())
    if "users" in tables:
        _add_missing_columns(
            "users",
            [
                sa.Column("llm_base_url", sa.String(512)),
                sa.Column("llm_api_key", sa.Text()),
                sa.Column("llm_model", sa.String(255)),
                sa.Column("llm_wire_api", sa.String(64)),
                sa.Column("llm_provider_protocol", sa.String(64)),
                sa.Column("llm_agent_provider", sa.String(64)),
                sa.Column("poi_llm_base_url", sa.String(512)),
                sa.Column("poi_llm_api_key", sa.Text()),
                sa.Column("poi_llm_model", sa.String(255)),
                sa.Column("poi_llm_wire_api", sa.String(64)),
                sa.Column("poi_llm_provider_protocol", sa.String(64)),
                sa.Column("image_base_url", sa.String(512)),
                sa.Column("image_api_key", sa.Text()),
                sa.Column("image_model", sa.String(255)),
                sa.Column("image_provider", sa.String(64)),
                sa.Column("search_service_provider", sa.String(64)),
                sa.Column("search_service_transport", sa.String(32)),
                sa.Column("search_service_base_url", sa.String(512)),
                sa.Column("search_service_api_key", sa.Text()),
                sa.Column("search_service_timeout_seconds", sa.Float(), nullable=False, server_default=sa.text("30")),
                sa.Column("xhs_source_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column("disabled_at", sa.DateTime(timezone=True)),
                sa.Column("disabled_reason", sa.Text()),
            ],
        )
    if "trips" in tables:
        _add_missing_columns("trips", [sa.Column("origin", sa.String(255), nullable=False, server_default="")])
    if "job_records" in tables:
        _add_missing_columns(
            "job_records",
            [
                sa.Column("stage", sa.String(64)),
                sa.Column("stage_message", sa.Text()),
                sa.Column("progress_percent", sa.Integer()),
                sa.Column("timeline_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            ],
        )


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind(), checkfirst=True)
