"""Appointment hold, confirm, cancel, and authorization tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.session import SessionLocal
from app.main import app
from app.models import Appointment
from app.models.enums import AppointmentStatus, UserRole
from app.services.auth import create_user_with_role

client = TestClient(app)

MONDAY_START = "2026-09-07T09:00:00+00:00"
MONDAY_END = "2026-09-07T09:30:00+00:00"
SLOT = {"start_datetime": MONDAY_START, "end_datetime": MONDAY_END}


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


def _freeze(moment: datetime) -> None:
    app.dependency_overrides[utc_now] = lambda: moment


@pytest.fixture()
def before_monday_hours() -> datetime:
    moment = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    _freeze(moment)
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


def _register_patient() -> tuple[str, str]:
    email = _email("patient")
    register = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "Test Patient"},
    )
    assert register.status_code == 201
    login = client.post("/api/auth/login", json={"email": email, "password": "securepass1"})
    return email, login.json()["access_token"]


def _create_doctor(admin_token: str, **overrides: object) -> dict:
    payload = {
        "email": _email("doctor"),
        "password": "securepass1",
        "full_name": "Dr Booking",
        "specialization": "General Medicine",
        "slot_duration_minutes": 30,
        "working_hours": [{"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00"}],
    }
    payload.update(overrides)
    response = client.post(
        "/api/admin/doctors",
        json=payload,
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _hold(token: str, doctor_id: int, client_obj: TestClient | None = None) -> object:
    http = client_obj or client
    return http.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor_id, **SLOT},
        headers=_auth_header(token),
    )


def _confirm(token: str, hold_id: int, client_obj: TestClient | None = None) -> object:
    http = client_obj or client
    return http.post(
        "/api/appointments/confirm",
        json={
            "hold_id": hold_id,
            "reason": "Checkup",
            "symptoms": "Routine checkup with mild fatigue.",
        },
        headers=_auth_header(token),
    )


def test_patient_can_hold_and_confirm(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _, token = _register_patient()
    hold = _hold(token, doctor["id"])
    assert hold.status_code == 201
    body = hold.json()
    assert body["status"] == "active"
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires == before_monday_hours + timedelta(minutes=5)

    confirmed = _confirm(token, body["id"])
    assert confirmed.status_code == 201
    appointment = confirmed.json()
    assert appointment["status"] == "confirmed"
    assert appointment["doctor_id"] == doctor["id"]
    listed = client.get("/api/appointments", headers=_auth_header(token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    fetched = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(token),
    )
    assert fetched.status_code == 200


def test_second_hold_on_same_slot_conflicts(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _, token_a = _register_patient()
    _, token_b = _register_patient()
    first = _hold(token_a, doctor["id"])
    second = _hold(token_b, doctor["id"])
    assert first.status_code == 201
    assert second.status_code == 409


def test_expired_hold_cannot_be_confirmed(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _, token = _register_patient()
    hold = _hold(token, doctor["id"])
    assert hold.status_code == 201
    _freeze(before_monday_hours + timedelta(minutes=6))
    confirmed = _confirm(token, hold.json()["id"])
    assert confirmed.status_code == 409


def test_patient_cannot_access_another_patient_appointment(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _, token_a = _register_patient()
    _, token_b = _register_patient()
    hold = _hold(token_a, doctor["id"])
    appointment = _confirm(token_a, hold.json()["id"]).json()
    listed = client.get("/api/appointments", headers=_auth_header(token_b))
    assert listed.json() == []
    blocked = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(token_b),
    )
    assert blocked.status_code == 403


def test_doctor_sees_only_own_appointments(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor_a = _create_doctor(admin_token)
    doctor_b = _create_doctor(admin_token)
    _, patient_token = _register_patient()
    hold = _hold(patient_token, doctor_a["id"])
    appointment = _confirm(patient_token, hold.json()["id"]).json()

    login_b = client.post(
        "/api/auth/login",
        json={"email": doctor_b["email"], "password": "securepass1"},
    )
    doctor_b_token = login_b.json()["access_token"]
    listed = client.get("/api/appointments", headers=_auth_header(doctor_b_token))
    assert listed.status_code == 200
    assert listed.json() == []
    blocked = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(doctor_b_token),
    )
    assert blocked.status_code == 403

    login_a = client.post(
        "/api/auth/login",
        json={"email": doctor_a["email"], "password": "securepass1"},
    )
    doctor_a_token = login_a.json()["access_token"]
    own = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(doctor_a_token),
    )
    assert own.status_code == 200


def test_admin_can_access_all_appointments(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _, token = _register_patient()
    hold = _hold(token, doctor["id"])
    appointment = _confirm(token, hold.json()["id"]).json()
    listed = client.get("/api/appointments", headers=_auth_header(admin_token))
    assert any(item["id"] == appointment["id"] for item in listed.json())
    fetched = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(admin_token),
    )
    assert fetched.status_code == 200


def test_cancel_preserves_history(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _, token = _register_patient()
    hold = _hold(token, doctor["id"])
    appointment = _confirm(token, hold.json()["id"]).json()
    cancelled = client.post(
        f"/api/appointments/{appointment['id']}/cancel",
        json={"reason": "Cannot attend"},
        headers=_auth_header(token),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    fetched = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(token),
    )
    assert fetched.json()["status"] == "cancelled"
    rehold = _hold(token, doctor["id"])
    assert rehold.status_code == 201


def test_doctor_cannot_hold_slot(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    login = client.post(
        "/api/auth/login",
        json={"email": doctor["email"], "password": "securepass1"},
    )
    response = _hold(login.json()["access_token"], doctor["id"])
    assert response.status_code == 403


def test_concurrent_booking_same_slot_returns_one_conflict(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _, token_a = _register_patient()
    _, token_b = _register_patient()
    doctor_id = doctor["id"]

    def book(token: str) -> int:
        local = TestClient(app)
        hold = _hold(token, doctor_id, local)
        if hold.status_code != 201:
            return hold.status_code
        confirm = _confirm(token, hold.json()["id"], local)
        return confirm.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(book, [token_a, token_b]))

    assert sorted(codes) == [201, 409]
    db.expire_all()
    start = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    count = db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.start_datetime == start,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
    )
    assert count == 1
