"""Authentication API tests."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_doctor, get_current_patient
from app.db.session import SessionLocal
from app.main import app
from app.models import User
from app.models.enums import UserRole
from app.schemas.auth import UserRegister
from app.services.auth import create_patient_user, create_user_with_role

client = TestClient(app)


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_patient(email: str | None = None, password: str = "securepass1") -> dict:
    payload = {
        "email": email or _email("patient"),
        "password": password,
        "full_name": "Test Patient",
    }
    response = client.post("/api/auth/register", json=payload)
    return {"response": response, "payload": payload}


def _login(email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


@pytest.fixture()
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_registration_creates_patient_only() -> None:
    result = _register_patient()
    response = result["response"]
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "patient"
    assert body["email"] == result["payload"]["email"]
    assert body["full_name"] == "Test Patient"
    assert body["is_active"] is True
    assert "hashed_password" not in body
    assert "password" not in body


def test_registration_ignores_requested_admin_role() -> None:
    email = _email("patient")
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "securepass1",
            "full_name": "Should Be Patient",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "patient"


def test_duplicate_email_returns_conflict() -> None:
    email = _email("dup")
    first = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "One"},
    )
    second = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "Two"},
    )
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "Email already registered"


def test_registration_rejects_short_password() -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": _email("short"), "password": "short", "full_name": "Test Patient"},
    )
    assert response.status_code == 422


def test_registration_rejects_invalid_email() -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "securepass1", "full_name": "Test Patient"},
    )
    assert response.status_code == 422


def test_registration_rejects_missing_fields() -> None:
    response = client.post("/api/auth/register", json={})
    assert response.status_code == 422


def _register_payload() -> UserRegister:
    return UserRegister(
        email=_email("integrity"),
        password="securepass1",
        full_name="Test Patient",
    )


def test_duplicate_email_integrity_error_on_flush_rolls_back() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    db.flush.side_effect = IntegrityError(
        "INSERT INTO users",
        {},
        Exception("duplicate key value violates unique constraint"),
    )
    with pytest.raises(ValueError, match="Email already registered"):
        create_patient_user(db, _register_payload())
    db.rollback.assert_called()
    db.commit.assert_not_called()


def test_registration_database_error_rolls_back_and_reraises() -> None:
    db = MagicMock()
    db.scalar.side_effect = ProgrammingError(
        "SELECT",
        {},
        Exception('relation "users" does not exist'),
    )
    with pytest.raises(ProgrammingError):
        create_patient_user(db, _register_payload())
    db.rollback.assert_called()
    db.commit.assert_not_called()


def test_registration_commit_failure_rolls_back_and_reraises() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    db.commit.side_effect = OperationalError("COMMIT", {}, Exception("server closed the connection"))
    with pytest.raises(OperationalError):
        create_patient_user(db, _register_payload())
    db.rollback.assert_called()


def test_login_returns_jwt() -> None:
    result = _register_patient()
    email = result["payload"]["email"]
    response = _login(email, "securepass1")
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "patient"


def test_login_wrong_password_returns_unauthorized() -> None:
    result = _register_patient()
    response = _login(result["payload"]["email"], "wrong-password")
    assert response.status_code == 401


def test_me_with_valid_token() -> None:
    result = _register_patient()
    token = _login(result["payload"]["email"], "securepass1").json()["access_token"]
    response = client.get("/api/auth/me", headers=_auth_header(token))
    assert response.status_code == 200
    assert response.json()["email"] == result["payload"]["email"]


def test_invalid_jwt_returns_unauthorized() -> None:
    response = client.get("/api/auth/me", headers=_auth_header("not-a-valid-jwt"))
    assert response.status_code == 401


def test_unauthorized_endpoint_without_token() -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    admin_response = client.get("/api/admin/dashboard")
    assert admin_response.status_code == 401


def test_patient_accessing_admin_endpoint_is_forbidden() -> None:
    result = _register_patient()
    token = _login(result["payload"]["email"], "securepass1").json()["access_token"]
    response = client.get("/api/admin/dashboard", headers=_auth_header(token))
    assert response.status_code == 403


def test_doctor_accessing_admin_endpoint_is_forbidden(db: Session) -> None:
    email = _email("doctor")
    create_user_with_role(
        db,
        email=email,
        password="securepass1",
        full_name="Test Doctor",
        role=UserRole.DOCTOR,
    )
    token = _login(email, "securepass1").json()["access_token"]
    response = client.get("/api/admin/dashboard", headers=_auth_header(token))
    assert response.status_code == 403


def test_admin_can_access_admin_endpoint(db: Session) -> None:
    email = _email("admin")
    create_user_with_role(
        db,
        email=email,
        password="securepass1",
        full_name="Test Admin",
        role=UserRole.ADMIN,
    )
    token = _login(email, "securepass1").json()["access_token"]
    response = client.get("/api/admin/dashboard", headers=_auth_header(token))
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_role_dependencies_enforce_roles() -> None:
    patient = User(
        id=1,
        email="patient@careconnect.test",
        hashed_password="x",
        full_name="Patient",
        role=UserRole.PATIENT,
        is_active=True,
    )
    doctor = User(
        id=2,
        email="doctor@careconnect.test",
        hashed_password="x",
        full_name="Doctor",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    admin = User(
        id=3,
        email="admin@careconnect.test",
        hashed_password="x",
        full_name="Admin",
        role=UserRole.ADMIN,
        is_active=True,
    )

    assert get_current_patient(patient).role == UserRole.PATIENT
    assert get_current_doctor(doctor).role == UserRole.DOCTOR
    assert get_current_admin(admin).role == UserRole.ADMIN

    with pytest.raises(HTTPException) as patient_exc:
        get_current_admin(patient)
    assert patient_exc.value.status_code == 403

    with pytest.raises(HTTPException) as doctor_exc:
        get_current_admin(doctor)
    assert doctor_exc.value.status_code == 403


def test_expired_jwt_returns_unauthorized() -> None:
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.core.config import settings

    token = jwt.encode(
        {
            "sub": "1",
            "role": "patient",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    response = client.get("/api/auth/me", headers=_auth_header(token))
    assert response.status_code == 401


def test_jwt_role_claim_does_not_override_database_role() -> None:
    from app.core.security import create_access_token

    result = _register_patient()
    me = client.get(
        "/api/auth/me",
        headers=_auth_header(_login(result["payload"]["email"], "securepass1").json()["access_token"]),
    )
    token = create_access_token(subject=str(me.json()["id"]), role="admin")
    response = client.get("/api/admin/dashboard", headers=_auth_header(token))
    assert response.status_code == 403
    allowed = client.get("/api/auth/me", headers=_auth_header(token))
    assert allowed.status_code == 200
    assert allowed.json()["role"] == "patient"

