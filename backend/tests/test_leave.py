"""Doctor leave processing: cancel affected visits without deleting history."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.session import SessionLocal
from app.main import app
from app.models import Appointment, NotificationLog
from app.models.enums import AppointmentStatus, UserRole
from app.services.auth import create_user_with_role

client = TestClient(app)

MONDAY = "2026-09-07"
SLOT_A = {
    "start_datetime": "2026-09-07T09:00:00+00:00",
    "end_datetime": "2026-09-07T09:30:00+00:00",
}
SLOT_B = {
    "start_datetime": "2026-09-07T09:30:00+00:00",
    "end_datetime": "2026-09-07T10:00:00+00:00",
}


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


@pytest.fixture(autouse=True)
def _reset_overrides() -> None:
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def before_monday_hours() -> datetime:
    moment = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    app.dependency_overrides[utc_now] = lambda: moment
    return moment


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
    response = client.post("/api/auth/login", json={"email": email, "password": "securepass1"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _register_patient() -> str:
    email = _email("patient")
    register = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "Leave Patient"},
    )
    assert register.status_code == 201
    login = client.post("/api/auth/login", json={"email": email, "password": "securepass1"})
    return login.json()["access_token"]


def _create_doctor(admin_token: str) -> dict:
    response = client.post(
        "/api/admin/doctors",
        json={
            "email": _email("doctor"),
            "password": "securepass1",
            "full_name": "Dr Leave",
            "specialization": "General Medicine",
            "slot_duration_minutes": 30,
            "working_hours": [
                {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00"},
            ],
        },
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 201
    return response.json()


def _book(token: str, doctor_id: int, slot: dict) -> dict:
    hold = client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor_id, **slot},
        headers=_auth_header(token),
    )
    assert hold.status_code == 201, hold.text
    confirmed = client.post(
        "/api/appointments/confirm",
        json={
            "hold_id": hold.json()["id"],
            "reason": "Checkup",
            "symptoms": "Routine checkup with mild fatigue.",
        },
        headers=_auth_header(token),
    )
    assert confirmed.status_code == 201, confirmed.text
    return confirmed.json()


def _create_leave(admin_token: str, doctor_id: int, reason: str = "Conference") -> object:
    return client.post(
        f"/api/admin/doctors/{doctor_id}/leave",
        json={"start_date": MONDAY, "end_date": MONDAY, "reason": reason},
        headers=_auth_header(admin_token),
    )


def test_leave_without_appointments(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    response = _create_leave(admin_token, doctor["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "processed"
    assert body["cancelled_appointment_ids"] == []
    db.expire_all()
    notes = db.scalars(
        select(NotificationLog).where(NotificationLog.user_id == doctor["user_id"])
    ).all()
    assert len(notes) == 1
    assert notes[0].notification_type == "doctor_leave_processed"


def test_leave_with_appointments_cancels_and_notifies(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    token = _register_patient()
    appointment = _book(token, doctor["id"], SLOT_A)
    response = _create_leave(admin_token, doctor["id"], reason="Training")
    assert response.status_code == 201
    assert appointment["id"] in response.json()["cancelled_appointment_ids"]

    fetched = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(token),
    )
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "cancelled_leave"
    assert "doctor is on leave" in body["cancellation_reason"]
    assert "Training" in body["cancellation_reason"]
    assert body["id"] == appointment["id"]
    assert body["start_datetime"]

    db.expire_all()
    persisted = db.get(Appointment, appointment["id"])
    assert persisted is not None
    assert persisted.status == AppointmentStatus.CANCELLED_LEAVE
    patient_notes = db.scalars(
        select(NotificationLog).where(
            NotificationLog.appointment_id == appointment["id"],
            NotificationLog.notification_type == "doctor_leave_cancellation",
        )
    ).all()
    assert len(patient_notes) == 1
    assert patient_notes[0].status in {"pending", "retrying", "failed"}


def test_leave_cancels_multiple_affected_appointments(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    token_a = _register_patient()
    token_b = _register_patient()
    first = _book(token_a, doctor["id"], SLOT_A)
    second = _book(token_b, doctor["id"], SLOT_B)
    response = _create_leave(admin_token, doctor["id"])
    assert response.status_code == 201
    cancelled = set(response.json()["cancelled_appointment_ids"])
    assert cancelled == {first["id"], second["id"]}
    for token, appointment_id in ((token_a, first["id"]), (token_b, second["id"])):
        body = client.get(
            f"/api/appointments/{appointment_id}",
            headers=_auth_header(token),
        ).json()
        assert body["status"] == "cancelled_leave"
        assert "doctor is on leave" in body["cancellation_reason"]


def test_booking_during_leave_is_rejected(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    leave = _create_leave(admin_token, doctor["id"])
    assert leave.status_code == 201
    token = _register_patient()
    hold = client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor["id"], **SLOT_A},
        headers=_auth_header(token),
    )
    assert hold.status_code == 409


def test_leave_preserves_appointment_history(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    token = _register_patient()
    appointment = _book(token, doctor["id"], SLOT_A)
    original_start = appointment["start_datetime"]
    original_id = appointment["id"]
    _create_leave(admin_token, doctor["id"])
    listed = client.get("/api/appointments", headers=_auth_header(token))
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == original_id
    assert rows[0]["start_datetime"] == original_start
    assert rows[0]["status"] == "cancelled_leave"
    db.expire_all()
    assert db.get(Appointment, original_id) is not None
