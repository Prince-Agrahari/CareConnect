"""Admin doctor management API tests."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models.enums import UserRole
from app.services.auth import create_user_with_role
from app.services.doctors import ensure_doctor_can_accept_bookings, get_doctor_or_404
from app.services.errors import ServiceError

client = TestClient(app)


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def admin_token(db: Session) -> str:
    email = _email("admin")
    create_user_with_role(
        db,
        email=email,
        password="securepass1",
        full_name="Admin User",
        role=UserRole.ADMIN,
    )
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "securepass1"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _patient_token() -> str:
    email = _email("patient")
    register = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "Patient User"},
    )
    assert register.status_code == 201
    login = client.post("/api/auth/login", json={"email": email, "password": "securepass1"})
    return login.json()["access_token"]


def _doctor_payload(**overrides: object) -> dict:
    payload = {
        "email": _email("doctor"),
        "password": "securepass1",
        "full_name": "Dr Example",
        "specialization": "Cardiology",
        "qualification": "MD",
        "bio": "Heart specialist",
        "slot_duration_minutes": 30,
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00"},
            {"day_of_week": 0, "start_time": "13:00:00", "end_time": "17:00:00"},
            {"day_of_week": 1, "start_time": "10:00:00", "end_time": "14:00:00"},
        ],
    }
    payload.update(overrides)
    return payload


def test_create_doctor_requires_admin(admin_token: str) -> None:
    response = client.post("/api/admin/doctors", json=_doctor_payload())
    assert response.status_code == 401

    patient_response = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(),
        headers=_auth_header(_patient_token()),
    )
    assert patient_response.status_code == 403

    created = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(),
        headers=_auth_header(admin_token),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["specialization"] == "Cardiology"
    assert body["qualification"] == "MD"
    assert body["slot_duration_minutes"] == 30
    assert body["is_active"] is True
    assert len(body["working_hours"]) == 3


def test_doctor_cannot_create_doctor(admin_token: str) -> None:
    created = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(),
        headers=_auth_header(admin_token),
    )
    assert created.status_code == 201
    doctor_login = client.post(
        "/api/auth/login",
        json={"email": created.json()["email"], "password": "securepass1"},
    )
    doctor_token = doctor_login.json()["access_token"]
    blocked = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(),
        headers=_auth_header(doctor_token),
    )
    assert blocked.status_code == 403


def test_admin_can_update_doctor_fields(admin_token: str) -> None:
    created = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(),
        headers=_auth_header(admin_token),
    )
    doctor_id = created.json()["id"]
    updated = client.patch(
        f"/api/admin/doctors/{doctor_id}",
        json={
            "specialization": "Dermatology",
            "qualification": "MBBS",
            "bio": "Skin specialist",
            "slot_duration_minutes": 15,
        },
        headers=_auth_header(admin_token),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["specialization"] == "Dermatology"
    assert body["qualification"] == "MBBS"
    assert body["bio"] == "Skin specialist"
    assert body["slot_duration_minutes"] == 15

    fetched = client.get(
        f"/api/admin/doctors/{doctor_id}",
        headers=_auth_header(admin_token),
    )
    assert fetched.status_code == 200
    assert fetched.json()["specialization"] == "Dermatology"


def test_activate_and_deactivate_doctor(admin_token: str, db: Session) -> None:
    created = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(),
        headers=_auth_header(admin_token),
    )
    doctor_id = created.json()["id"]
    deactivated = client.post(
        f"/api/admin/doctors/{doctor_id}/deactivate",
        headers=_auth_header(admin_token),
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    db.expire_all()
    doctor = get_doctor_or_404(db, doctor_id)
    with pytest.raises(ServiceError) as exc:
        ensure_doctor_can_accept_bookings(doctor)
    assert exc.value.status_code == 409
    assert "Inactive doctors cannot accept new bookings" in exc.value.detail

    activated = client.post(
        f"/api/admin/doctors/{doctor_id}/activate",
        headers=_auth_header(admin_token),
    )
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True
    db.expire_all()
    ensure_doctor_can_accept_bookings(get_doctor_or_404(db, doctor_id))


def test_invalid_slot_duration_rejected(admin_token: str) -> None:
    too_small = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(slot_duration_minutes=3),
        headers=_auth_header(admin_token),
    )
    too_large = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(slot_duration_minutes=200),
        headers=_auth_header(admin_token),
    )
    assert too_small.status_code == 422
    assert too_large.status_code == 422


def test_working_hours_start_must_be_before_end(admin_token: str) -> None:
    response = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(
            working_hours=[
                {"day_of_week": 0, "start_time": "17:00:00", "end_time": "09:00:00"},
            ]
        ),
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 422


def test_overlapping_working_hours_rejected(admin_token: str) -> None:
    response = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(
            working_hours=[
                {"day_of_week": 0, "start_time": "09:00:00", "end_time": "13:00:00"},
                {"day_of_week": 0, "start_time": "12:00:00", "end_time": "17:00:00"},
            ]
        ),
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 409


def test_replace_working_hours_per_weekday(admin_token: str) -> None:
    created = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(working_hours=[]),
        headers=_auth_header(admin_token),
    )
    doctor_id = created.json()["id"]
    updated = client.put(
        f"/api/admin/doctors/{doctor_id}/working-hours",
        json={
            "hours": [
                {"day_of_week": 0, "start_time": "09:00:00", "end_time": "17:00:00"},
                {"day_of_week": 2, "start_time": "08:00:00", "end_time": "12:00:00"},
            ]
        },
        headers=_auth_header(admin_token),
    )
    assert updated.status_code == 200
    days = [item["day_of_week"] for item in updated.json()["working_hours"]]
    assert days == [0, 2]


def test_create_doctor_leave(admin_token: str) -> None:
    created = client.post(
        "/api/admin/doctors",
        json=_doctor_payload(),
        headers=_auth_header(admin_token),
    )
    doctor_id = created.json()["id"]
    leave = client.post(
        f"/api/admin/doctors/{doctor_id}/leaves",
        json={"start_date": "2026-10-01", "end_date": "2026-10-03", "reason": "Conference"},
        headers=_auth_header(admin_token),
    )
    assert leave.status_code == 201
    assert leave.json()["status"] == "processed"
    assert leave.json()["cancelled_appointment_ids"] == []

    overlap = client.post(
        f"/api/admin/doctors/{doctor_id}/leaves",
        json={"start_date": "2026-10-03", "end_date": "2026-10-04", "reason": "Overlap"},
        headers=_auth_header(admin_token),
    )
    assert overlap.status_code == 409


def test_patient_cannot_view_admin_doctor_list(admin_token: str) -> None:
    listed = client.get("/api/admin/doctors", headers=_auth_header(_patient_token()))
    assert listed.status_code == 403
    allowed = client.get("/api/admin/doctors", headers=_auth_header(admin_token))
    assert allowed.status_code == 200
