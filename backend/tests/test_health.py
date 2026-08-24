"""Health endpoint tests. These do not require PostgreSQL."""

from fastapi.testclient import TestClient

from app.core.config import REQUIRED_CORS_ORIGINS, parse_cors_origins
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


def test_parse_cors_origins_empty_uses_required_frontends() -> None:
    assert parse_cors_origins("") == list(REQUIRED_CORS_ORIGINS)
    assert parse_cors_origins("   ") == list(REQUIRED_CORS_ORIGINS)
    assert parse_cors_origins(None) == list(REQUIRED_CORS_ORIGINS)


def test_parse_cors_origins_keeps_required_frontends() -> None:
    parsed = parse_cors_origins("http://localhost:5173")
    assert parsed == list(REQUIRED_CORS_ORIGINS)


def test_parse_cors_origins_splits_and_strips() -> None:
    parsed = parse_cors_origins(
        ' http://localhost:5173, "https://careconnect-frontend-32l4.onrender.com/" '
    )
    assert parsed == [
        "http://localhost:5173",
        "https://careconnect-frontend-32l4.onrender.com",
    ]


def test_cors_preflight_allows_deployed_frontend() -> None:
    response = client.options(
        "/api/auth/register",
        headers={
            "Origin": "https://careconnect-frontend-32l4.onrender.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    assert response.headers.get("access-control-allow-origin") == (
        "https://careconnect-frontend-32l4.onrender.com"
    )
    assert response.status_code == 200
