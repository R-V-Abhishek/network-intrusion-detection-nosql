"""Flask API tests using the real app factory with a mock storage backend."""

from __future__ import annotations

import dashboard.app as app_module


class MockStorage:
    """Minimal in-memory stand-in for AlertStorage."""

    def __init__(self) -> None:
        self.connected = False
        self.sessions = []

    def connect(self) -> None:
        self.connected = True

    def register_session(self, session_id: str, dataset: str) -> None:
        self.sessions.append({"session_id": session_id, "dataset": dataset})

    def get_sessions(self, limit: int = 10):
        return self.sessions[:limit]

    def delete_session(self, session_id: str) -> dict:
        return {"session_id": session_id, "removed_alerts": 0, "session_removed": True}

    def delete_all_sessions(self) -> dict:
        return {"removed_sessions": len(self.sessions), "removed_alerts": 0}


def _make_client(monkeypatch):
    storage = MockStorage()
    monkeypatch.setattr(app_module, "get_storage", lambda: storage)
    monkeypatch.setattr(app_module, "get_current_session_id", lambda: "sess-1")
    monkeypatch.setattr(app_module, "start_new_session", lambda: "sess-2")

    app = app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client(), storage


def test_api_health(monkeypatch):
    client, storage = _make_client(monkeypatch)
    response = client.get("/api/health")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["services"] == {"storage": "connected"}
    assert isinstance(payload["commit"], str)
    assert storage.connected is True


def test_api_session_current(monkeypatch):
    client, storage = _make_client(monkeypatch)
    response = client.get("/api/session/current")

    assert response.status_code == 200
    assert response.get_json() == {"session_id": "sess-1"}
    assert storage.sessions[0]["session_id"] == "sess-1"


def test_api_session_new(monkeypatch):
    client, storage = _make_client(monkeypatch)
    response = client.post("/api/session/new")

    assert response.status_code == 200
    assert response.get_json() == {"session_id": "sess-2"}
    assert storage.sessions[-1]["session_id"] == "sess-2"
