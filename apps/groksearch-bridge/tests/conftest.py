import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY", "bridge-key")
    monkeypatch.setenv("TRAVELMIND_GROKSEARCH_COMMAND", "python -m grok_search.server")

    for name in list(sys.modules):
        if name.startswith("travelmind_groksearch_bridge"):
            del sys.modules[name]

    from travelmind_groksearch_bridge.main import close_runner, create_app

    app = create_app()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        close_runner()
