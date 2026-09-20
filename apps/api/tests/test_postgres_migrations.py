from __future__ import annotations

import os
from typing import TypedDict

import pytest
from alembic import command
from langgraph.graph import END, START, StateGraph
from sqlalchemy import create_engine, inspect, text

from travelmind_api.core.config import Settings
from travelmind_api.core.database import alembic_config
from travelmind_api.services.workflow_store import workflow_checkpointer


POSTGRES_URL = os.getenv("TRAVELMIND_TEST_POSTGRES_URL", "").strip()


@pytest.mark.skipif(not POSTGRES_URL, reason="TRAVELMIND_TEST_POSTGRES_URL is not configured")
def test_postgres_upgrade_downgrade_cycle():
    config = alembic_config(POSTGRES_URL)
    command.upgrade(config, "head")

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    inspector = inspect(engine)
    assert {"users", "trips", "job_records", "workflow_runs", "alembic_version"}.issubset(
        inspector.get_table_names()
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0005_workflow_runs"
    assert "workflow_run_id" in {column["name"] for column in inspector.get_columns("job_records")}

    command.downgrade(config, "base")
    assert "users" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "users" in inspect(engine).get_table_names()
    engine.dispose()


@pytest.mark.skipif(not POSTGRES_URL, reason="TRAVELMIND_TEST_POSTGRES_URL is not configured")
def test_postgres_checkpointer_resumes_after_connection_restart():
    class RecoveryState(TypedDict, total=False):
        first: str
        second: str

    calls = {"first": 0, "second": 0}
    fail_second = True

    def build_graph(saver):
        def first(_state):
            calls["first"] += 1
            return {"first": "preserved"}

        def second(_state):
            calls["second"] += 1
            if fail_second:
                raise RuntimeError("simulated PostgreSQL worker interruption")
            return {"second": "recovered"}

        builder = StateGraph(RecoveryState)
        builder.add_node("first", first)
        builder.add_node("second", second)
        builder.add_edge(START, "first")
        builder.add_edge("first", "second")
        builder.add_edge("second", END)
        return builder.compile(checkpointer=saver)

    checkpoint_url = POSTGRES_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    settings = Settings(environment="test", workflow_checkpoint_url=checkpoint_url)
    config = {"configurable": {"thread_id": "postgres-checkpointer-recovery"}}

    with workflow_checkpointer(settings) as saver:
        with pytest.raises(RuntimeError, match="worker interruption"):
            build_graph(saver).invoke({}, config=config)

    fail_second = False
    with workflow_checkpointer(settings) as saver:
        result = build_graph(saver).invoke(None, config=config)

    assert result == {"first": "preserved", "second": "recovered"}
    assert calls == {"first": 1, "second": 2}
