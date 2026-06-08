import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVELMIND_DATABASE_URL", f"sqlite:///{(tmp_path / 'travelmind.db').as_posix()}")
    monkeypatch.setenv("TRAVELMIND_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.setenv("TRAVELMIND_QUEUE_MODE", "inline")
    monkeypatch.setenv("TRAVELMIND_AGENT_PROVIDER", "stub")
    monkeypatch.setenv("TRAVELMIND_PUBLIC_API_URL", "http://testserver")

    for name in list(sys.modules):
        if name.startswith("travelmind_api"):
            del sys.modules[name]

    from travelmind_api.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
