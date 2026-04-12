from fastapi.testclient import TestClient

from witty_service.main import create_app


def test_agents_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-token")
    client = TestClient(create_app())

    resp = client.get("/api/v1/agents")

    assert resp.status_code == 401


def test_agents_accepts_valid_bearer_token(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-token")
    client = TestClient(create_app())

    resp = client.get("/api/v1/agents", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    assert resp.json() == []


def test_agents_accepts_lowercase_bearer_token(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-token")
    client = TestClient(create_app())

    resp = client.get("/api/v1/agents", headers={"Authorization": "bearer test-token"})

    assert resp.status_code == 200
    assert resp.json() == []


def test_agents_rejects_wrong_bearer_token(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-token")
    client = TestClient(create_app())

    resp = client.get("/api/v1/agents", headers={"Authorization": "Bearer wrong-token"})

    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
