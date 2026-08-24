"""Availability slot generation tests. The backend is the source of truth."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.session import SessionLocal
from app.main import app
from app.models import Appointment, AppointmentSlotHold, PatientProfile
from app.models.enums import AppointmentStatus, SlotHoldStatus, UserRole
from app.services.auth import create_user_with_role

client = TestClient(app)

MONDAY = "2026-09-07"
TUESDAY = "2026-09-08"
SATURDAY = "2026-09-12"
SUNDAY = "2026-09-13"
PAST_SUNDAY = "2026-09-06"


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
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "securepass1"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _create_doctor(
    admin_token: str,
    *,
    slot_duration_minutes: int = 30,
    working_hours: list[dict] | None = None,
    is_active: bool = True,
) -> dict:
    payload = {
        "email": _email("doctor"),
        "password": "securepass1",
        "full_name": "Dr Availability",
        "specialization": "General Medicine",
        "slot_duration_minutes": slot_duration_minutes,
        "is_active": is_active,
        "working_hours": working_hours
        if working_hours is not None
        else [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00"},
        ],
    }
    response = client.post(
        "/api/admin/doctors",
        json=payload,
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_patient(db: Session) -> PatientProfile:
    email = _email("patient")
    register = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "Slot Patient"},
    )
    assert register.status_code == 201
    user_id = register.json()["id"]
    profile = db.scalar(select(PatientProfile).where(PatientProfile.user_id == user_id))
    assert profile is not None
    return profile


def _parse(moment: str) -> datetime:
    return datetime.fromisoformat(moment.replace("Z", "+00:00"))


def _starts(payload: dict) -> list[datetime]:
    return [_parse(slot["start_datetime"]) for slot in payload["slots"]]


def test_unknown_doctor_returns_404(before_monday_hours: datetime) -> None:
    response = client.get("/api/doctors/999999/availability", params={"date": MONDAY})
    assert response.status_code == 404


def test_slots_follow_working_hours_and_duration(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": MONDAY},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slot_duration_minutes"] == 30
    assert body["is_active"] is True
    assert _starts(body) == [
        datetime(2026, 9, 7, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 7, 9, 30, tzinfo=UTC),
        datetime(2026, 9, 7, 10, 0, tzinfo=UTC),
        datetime(2026, 9, 7, 10, 30, tzinfo=UTC),
        datetime(2026, 9, 7, 11, 0, tzinfo=UTC),
        datetime(2026, 9, 7, 11, 30, tzinfo=UTC),
    ]


def test_weekend_without_hours_has_no_slots(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    saturday = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": SATURDAY},
    )
    sunday = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": SUNDAY},
    )
    assert saturday.status_code == 200
    assert sunday.status_code == 200
    assert saturday.json()["slots"] == []
    assert sunday.json()["slots"] == []


def test_weekend_with_hours_has_slots(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(
        admin_token,
        working_hours=[
            {"day_of_week": 5, "start_time": "09:00:00", "end_time": "10:00:00"},
        ],
    )
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": SATURDAY},
    )
    assert _starts(response.json()) == [
        datetime(2026, 9, 12, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 12, 9, 30, tzinfo=UTC),
    ]


def test_leave_day_has_no_slots(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    leave = client.post(
        f"/api/admin/doctors/{doctor['id']}/leaves",
        json={"start_date": MONDAY, "end_date": TUESDAY, "reason": "Conference"},
        headers=_auth_header(admin_token),
    )
    assert leave.status_code == 201
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": MONDAY},
    )
    assert response.json()["slots"] == []


def test_past_date_has_no_slots(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(
        admin_token,
        working_hours=[
            {"day_of_week": 6, "start_time": "09:00:00", "end_time": "12:00:00"},
        ],
    )
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": PAST_SUNDAY},
    )
    assert response.status_code == 200
    assert response.json()["slots"] == []


def test_past_times_today_are_excluded(admin_token: str) -> None:
    _freeze(datetime(2026, 9, 7, 10, 15, tzinfo=UTC))
    doctor = _create_doctor(admin_token)
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": MONDAY},
    )
    assert _starts(response.json()) == [
        datetime(2026, 9, 7, 10, 30, tzinfo=UTC),
        datetime(2026, 9, 7, 11, 0, tzinfo=UTC),
        datetime(2026, 9, 7, 11, 30, tzinfo=UTC),
    ]


def test_existing_appointment_blocks_slot(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    patient = _create_patient(db)
    db.add(
        Appointment(
            patient_id=patient.id,
            doctor_id=doctor["id"],
            start_datetime=datetime(2026, 9, 7, 9, 30, tzinfo=UTC),
            end_datetime=datetime(2026, 9, 7, 10, 0, tzinfo=UTC),
            status=AppointmentStatus.CONFIRMED,
            reason="Checkup",
        )
    )
    db.commit()
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": MONDAY},
    )
    starts = _starts(response.json())
    assert datetime(2026, 9, 7, 9, 30, tzinfo=UTC) not in starts
    assert datetime(2026, 9, 7, 9, 0, tzinfo=UTC) in starts
    assert datetime(2026, 9, 7, 10, 0, tzinfo=UTC) in starts


def test_cancelled_appointment_does_not_block_slot(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    patient = _create_patient(db)
    db.add(
        Appointment(
            patient_id=patient.id,
            doctor_id=doctor["id"],
            start_datetime=datetime(2026, 9, 7, 9, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 9, 7, 9, 30, tzinfo=UTC),
            status=AppointmentStatus.CANCELLED,
            reason="Cancelled",
        )
    )
    db.commit()
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": MONDAY},
    )
    assert datetime(2026, 9, 7, 9, 0, tzinfo=UTC) in _starts(response.json())


def test_active_hold_blocks_slot(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    patient = _create_patient(db)
    db.add(
        AppointmentSlotHold(
            patient_id=patient.id,
            doctor_id=doctor["id"],
            start_datetime=datetime(2026, 9, 7, 11, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 9, 7, 11, 30, tzinfo=UTC),
            expires_at=before_monday_hours + timedelta(minutes=10),
            status=SlotHoldStatus.ACTIVE,
        )
    )
    db.commit()
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": MONDAY},
    )
    assert datetime(2026, 9, 7, 11, 0, tzinfo=UTC) not in _starts(response.json())
    assert datetime(2026, 9, 7, 11, 30, tzinfo=UTC) in _starts(response.json())


def test_expired_hold_does_not_block_slot(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    patient = _create_patient(db)
    db.add(
        AppointmentSlotHold(
            patient_id=patient.id,
            doctor_id=doctor["id"],
            start_datetime=datetime(2026, 9, 7, 11, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 9, 7, 11, 30, tzinfo=UTC),
            expires_at=before_monday_hours - timedelta(minutes=1),
            status=SlotHoldStatus.ACTIVE,
        )
    )
    db.commit()
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": MONDAY},
    )
    assert datetime(2026, 9, 7, 11, 0, tzinfo=UTC) in _starts(response.json())


def test_inactive_doctor_has_no_slots(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token, is_active=False)
    response = client.get(
        f"/api/doctors/{doctor['id']}/availability",
        params={"date": MONDAY},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["slots"] == []
