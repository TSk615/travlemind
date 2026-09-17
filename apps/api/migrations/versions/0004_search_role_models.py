"""Add independent model selection for search-backed specialist roles."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_search_role_models"
down_revision = "0003_trip_budget_numeric"
branch_labels = None
depends_on = None


POI_MULTI_AGENT_MODEL = "Console/grok-4.20-multi-agent-0309"
WEATHER_FAST_MODEL = "Web/grok-chat-fast"
REASONING_MODEL = "Console/grok-4.20-0309-reasoning"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("weather_llm_model", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("hotel_llm_model", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("transport_llm_model", sa.String(255), nullable=True))

    # Existing Web Fast installations move to the audited role routing agreed for
    # this project. Other providers retain their current model for every role.
    op.execute(
        sa.text(
            """
            UPDATE users
            SET poi_llm_model = :poi_model,
                weather_llm_model = :weather_model,
                hotel_llm_model = :reasoning_model,
                transport_llm_model = :reasoning_model,
                poi_llm_wire_api = 'responses'
            WHERE poi_llm_model = 'Web/grok-chat-fast'
              AND poi_llm_base_url IS NOT NULL
              AND poi_llm_api_key IS NOT NULL
            """
        ).bindparams(
            poi_model=POI_MULTI_AGENT_MODEL,
            weather_model=WEATHER_FAST_MODEL,
            reasoning_model=REASONING_MODEL,
        )
    )
    op.execute(
        """
        UPDATE users
        SET weather_llm_model = COALESCE(weather_llm_model, poi_llm_model),
            hotel_llm_model = COALESCE(hotel_llm_model, poi_llm_model),
            transport_llm_model = COALESCE(transport_llm_model, poi_llm_model)
        WHERE poi_llm_model IS NOT NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("transport_llm_model")
        batch_op.drop_column("hotel_llm_model")
        batch_op.drop_column("weather_llm_model")
