from __future__ import annotations

from contextlib import contextmanager

import pytest

from travelmind_api.core.config import Settings
import travelmind_api.services.workflow_store as workflow_store


def test_postgres_checkpointer_setup_uses_cross_process_advisory_lock(monkeypatch):
    events: list[object] = []

    class FakeCursor:
        def execute(self, statement, parameters):
            events.append((statement, parameters))

    class FakeConnection:
        @contextmanager
        def cursor(self):
            yield FakeCursor()

        def close(self):
            events.append("close")

    class FakeSaver:
        def __init__(self, connection, *, serde):
            assert isinstance(connection, FakeConnection)
            assert serde is not None

        def setup(self):
            events.append("setup")

    checkpoint_url = "postgresql://workflow.test/travelmind"
    workflow_store._POSTGRES_SETUP_URLS.discard(checkpoint_url)
    monkeypatch.setattr(workflow_store.psycopg, "connect", lambda *args, **kwargs: FakeConnection())
    monkeypatch.setattr(workflow_store, "PostgresSaver", FakeSaver)

    settings = Settings(environment="test", workflow_checkpoint_url=checkpoint_url)
    with workflow_store.workflow_checkpointer(settings) as saver:
        assert isinstance(saver, FakeSaver)

    assert events == [
        ("SELECT pg_advisory_lock(%s)", (workflow_store._POSTGRES_CHECKPOINT_SETUP_LOCK_ID,)),
        "setup",
        ("SELECT pg_advisory_unlock(%s)", (workflow_store._POSTGRES_CHECKPOINT_SETUP_LOCK_ID,)),
        "close",
    ]
    workflow_store._POSTGRES_SETUP_URLS.discard(checkpoint_url)


def test_postgres_checkpointer_setup_failure_releases_advisory_lock(monkeypatch):
    events: list[str] = []

    class FakeCursor:
        def execute(self, statement, _parameters):
            events.append(statement)

    class FakeConnection:
        @contextmanager
        def cursor(self):
            yield FakeCursor()

        def close(self):
            events.append("close")

    class FailingSaver:
        def __init__(self, _connection, *, serde):
            assert serde is not None

        def setup(self):
            events.append("setup")
            raise RuntimeError("checkpoint setup failed")

    checkpoint_url = "postgresql://workflow-failure.test/travelmind"
    workflow_store._POSTGRES_SETUP_URLS.discard(checkpoint_url)
    monkeypatch.setattr(workflow_store.psycopg, "connect", lambda *args, **kwargs: FakeConnection())
    monkeypatch.setattr(workflow_store, "PostgresSaver", FailingSaver)

    with pytest.raises(RuntimeError, match="checkpoint setup failed"):
        with workflow_store.workflow_checkpointer(
            Settings(environment="test", workflow_checkpoint_url=checkpoint_url)
        ):
            pass

    assert events == [
        "SELECT pg_advisory_lock(%s)",
        "setup",
        "SELECT pg_advisory_unlock(%s)",
        "close",
    ]
    assert checkpoint_url not in workflow_store._POSTGRES_SETUP_URLS
