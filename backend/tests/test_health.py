"""Health endpoint tests. These do not require PostgreSQL."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "CareConnect"
    assert payload["message"] == "CareConnect API is running"


def test_versioned_health_check_returns_ok() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "CareConnect"


def test_openapi_docs_available() -> None:
    response = client.get("/docs")
    assert response.status_code == 200
