"""Cancellation and reschedule: authorization, history, concurrency, and side-effect isolation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.clock import utc_now
from app.db.session import SessionLocal
from app.integrations.calendar import CalendarError, set_calendar_client
from app.integrations.email import EmailError, set_email_client
from app.main import app
from app.models import Appointment, CalendarEvent, CalendarIntegration, NotificationLog
from app.models.enums import (
    AppointmentStatus,
    CalendarProvider,
    CalendarSyncStatus,
    NotificationStatus,
    NotificationType,
    UserRole,
)
from app.services.auth import create_user_with_role

client = TestClient(app)

SLOT_A = {
    "start_datetime": "2026-09-07T09:00:00+00:00",
    "end_datetime": "2026-09-07T09:30:00+00:00",
}
SLOT_B = {
    "start_datetime": "2026-09-07T09:30:00+00:00",
    "end_datetime": "2026-09-07T10:00:00+00:00",
}
SLOT_C = {
    "start_datetime": "2026-09-07T10:00:00+00:00",
    "end_datetime": "2026-09-07T10:30:00+00:00",
}
SYMPTOMS = "Headache for three days."


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeEmail:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, str]] = []

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        if self.fail:
            raise EmailError("SendGrid unavailable")
        self.calls.append({"recipient": recipient, "subject": subject, "body": body})


class _FakeCalendar:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.upserts: list[dict] = []
        self.deletes: list[dict] = []

    def upsert_event(self, **kwargs: object) -> str:
        if self.fail:
            raise CalendarError("Google Calendar unavailable")
        self.upserts.append(kwargs)
        existing = kwargs.get("provider_event_id")
        if isinstance(existing, str) and existing:
            return existing
        return f"gcal-{len(self.upserts)}"

    def delete_event(self, **kwargs: object) -> None:
        if self.fail:
            raise CalendarError("Google Calendar unavailable")
        self.deletes.append(kwargs)


@pytest.fixture()
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_overrides() -> tuple[_FakeEmail, _FakeCalendar]:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    mail = _FakeEmail()
    gcal = _FakeCalendar()
    set_email_client(mail)
    set_calendar_client(gcal)
    yield mail, gcal
    set_email_client(None)
    set_calendar_client(None)
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    app.dependency_overrides.clear()


@pytest.fixture()
def mail(_reset_overrides: tuple[_FakeEmail, _FakeCalendar]) -> _FakeEmail:
    return _reset_overrides[0]


@pytest.fixture()
def gcal(_reset_overrides: tuple[_FakeEmail, _FakeCalendar]) -> _FakeCalendar:
    return _reset_overrides[1]


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
    return response.json()["access_token"]


def _register_patient() -> tuple[str, str]:
    email = _email("patient")
    register = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "Cancel Patient"},
    )
    assert register.status_code == 201
    login = client.post("/api/auth/login", json={"email": email, "password": "securepass1"})
    return email, login.json()["access_token"]


def _create_doctor(admin_token: str) -> dict:
    response = client.post(
        "/api/admin/doctors",
        json={
            "email": _email("doctor"),
            "password": "securepass1",
            "full_name": "Dr Cancel",
            "specialization": "General Medicine",
            "slot_duration_minutes": 30,
            "working_hours": [{"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00"}],
        },
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 201
    return response.json()


def _book(patient_token: str, doctor_id: int, slot: dict | None = None) -> dict:
    hold = client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor_id, **(slot or SLOT_A)},
        headers=_auth_header(patient_token),
    )
    assert hold.status_code == 201, hold.text
    confirmed = client.post(
        "/api/appointments/confirm",
        json={"hold_id": hold.json()["id"], "reason": "Checkup", "symptoms": SYMPTOMS},
        headers=_auth_header(patient_token),
    )
    assert confirmed.status_code == 201, confirmed.text
    return confirmed.json()


def _hold(token: str, doctor_id: int, slot: dict, client_obj: TestClient | None = None) -> object:
    http = client_obj or client
    return http.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor_id, **slot},
        headers=_auth_header(token),
    )


def _connect(db: Session, user_id: int) -> CalendarIntegration:
    row = CalendarIntegration(
        user_id=user_id,
        provider=CalendarProvider.GOOGLE,
        access_token="access-token",
        refresh_token="refresh-token",
        google_calendar_id="primary",
        is_connected=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_cancellation(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    mail: _FakeEmail,
    gcal: _FakeCalendar,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, patient["id"])
    appointment = _book(token, doctor["id"])
    original_start = appointment["start_datetime"]
    original_end = appointment["end_datetime"]
    mail.calls.clear()
    cancelled = client.post(
        f"/api/appointments/{appointment['id']}/cancel",
        json={"reason": "Cannot attend"},
        headers=_auth_header(token),
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["id"] == appointment["id"]
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "Cannot attend"
    assert body["cancelled_at"] is not None
    assert body["start_datetime"] == original_start
    assert body["end_datetime"] == original_end
    fetched = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(token),
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "cancelled"
    db.expire_all()
    stored = db.get(Appointment, appointment["id"])
    assert stored is not None
    assert stored.status == AppointmentStatus.CANCELLED
    rehold = _hold(token, doctor["id"], SLOT_A)
    assert rehold.status_code == 201
    logs = list(
        db.scalars(
            select(NotificationLog).where(
                NotificationLog.appointment_id == appointment["id"],
                NotificationLog.notification_type == NotificationType.APPOINTMENT_CANCELLATION,
            )
        )
    )
    assert len(logs) == 1
    assert logs[0].status == NotificationStatus.SENT
    assert any("cancelled" in call["subject"].lower() for call in mail.calls)
    events = list(
        db.scalars(select(CalendarEvent).where(CalendarEvent.appointment_id == appointment["id"]))
    )
    assert len(events) == 1
    assert events[0].sync_status == CalendarSyncStatus.DELETED
    assert len(gcal.deletes) == 1


def test_unauthorized_cancellation(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    other_doctor = _create_doctor(admin_token)
    _email_a, token_a = _register_patient()
    _email_b, token_b = _register_patient()
    appointment = _book(token_a, doctor["id"])

    missing = client.post(
        f"/api/appointments/{appointment['id']}/cancel",
        json={"reason": "Cannot attend"},
    )
    assert missing.status_code == 401

    other_patient = client.post(
        f"/api/appointments/{appointment['id']}/cancel",
        json={"reason": "Cannot attend"},
        headers=_auth_header(token_b),
    )
    assert other_patient.status_code == 403

    other_login = client.post(
        "/api/auth/login",
        json={"email": other_doctor["email"], "password": "securepass1"},
    )
    other_doctor_token = other_login.json()["access_token"]
    other_doc = client.post(
        f"/api/appointments/{appointment['id']}/cancel",
        json={"reason": "Cannot attend"},
        headers=_auth_header(other_doctor_token),
    )
    assert other_doc.status_code == 403

    still = client.get(
        f"/api/appointments/{appointment['id']}",
        headers=_auth_header(token_a),
    )
    assert still.json()["status"] == "confirmed"


def test_rescheduling(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    mail: _FakeEmail,
    gcal: _FakeCalendar,
) -> None:
    doctor = _create_doctor(admin_token)
    patient_email, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, patient["id"])
    appointment = _book(token, doctor["id"], SLOT_A)
    hold = _hold(token, doctor["id"], SLOT_B)
    assert hold.status_code == 201, hold.text
    mail.calls.clear()
    gcal.upserts.clear()
    moved = client.post(
        f"/api/appointments/{appointment['id']}/reschedule",
        json={"hold_id": hold.json()["id"]},
        headers=_auth_header(token),
    )
    assert moved.status_code == 201, moved.text
    body = moved.json()
    assert body["id"] != appointment["id"]
    assert body["status"] == "confirmed"
    assert datetime.fromisoformat(body["start_datetime"].replace("Z", "+00:00")) == datetime.fromisoformat(
        SLOT_B["start_datetime"]
    )
    assert datetime.fromisoformat(body["end_datetime"].replace("Z", "+00:00")) == datetime.fromisoformat(
        SLOT_B["end_datetime"]
    )
    assert body["rescheduled_from_appointment_id"] == appointment["id"]
    db.expire_all()
    previous = db.get(Appointment, appointment["id"])
    replacement = db.get(Appointment, body["id"])
    assert previous is not None
    assert replacement is not None
    assert previous.status == AppointmentStatus.RESCHEDULED
    assert previous.start_datetime == datetime.fromisoformat(SLOT_A["start_datetime"])
    assert replacement.status == AppointmentStatus.CONFIRMED
    old_slot = _hold(token, doctor["id"], SLOT_A)
    assert old_slot.status_code == 201
    taken = client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor["id"], **SLOT_B},
        headers=_auth_header(token),
    )
    assert taken.status_code == 409
    logs = list(
        db.scalars(
            select(NotificationLog).where(
                NotificationLog.appointment_id == body["id"],
                NotificationLog.notification_type == NotificationType.APPOINTMENT_RESCHEDULED,
            )
        )
    )
    assert len(logs) == 2
    assert {row.recipient for row in logs} == {patient_email, doctor["email"]}
    assert len([call for call in mail.calls if "rescheduled" in call["subject"].lower()]) == 2
    new_events = list(
        db.scalars(select(CalendarEvent).where(CalendarEvent.appointment_id == body["id"]))
    )
    assert len(new_events) == 1
    assert new_events[0].sync_status == CalendarSyncStatus.SYNCED
    assert gcal.upserts
    assert gcal.upserts[-1]["start"] == datetime.fromisoformat(SLOT_B["start_datetime"])


def test_simultaneous_rescheduling(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    appointment = _book(token, doctor["id"], SLOT_A)
    hold_b = _hold(token, doctor["id"], SLOT_B)
    hold_c = _hold(token, doctor["id"], SLOT_C)
    assert hold_b.status_code == 201, hold_b.text
    assert hold_c.status_code == 201, hold_c.text
    appointment_id = appointment["id"]
    doctor_id = doctor["id"]
    hold_ids = [hold_b.json()["id"], hold_c.json()["id"]]

    def move(hold_id: int) -> int:
        local = TestClient(app)
        response = local.post(
            f"/api/appointments/{appointment_id}/reschedule",
            json={"hold_id": hold_id},
            headers=_auth_header(token),
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(move, hold_ids))

    assert sorted(codes) == [201, 409]
    db.expire_all()
    previous = db.get(Appointment, appointment_id)
    assert previous is not None
    assert previous.status == AppointmentStatus.RESCHEDULED
    confirmed = list(
        db.scalars(
            select(Appointment).where(
                Appointment.doctor_id == doctor_id,
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.rescheduled_from_appointment_id == appointment_id,
            )
        )
    )
    assert len(confirmed) == 1
    count = db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
    )
    assert count == 1


def test_calendar_failure_does_not_undo_cancel_or_reschedule(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    gcal: _FakeCalendar,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, patient["id"])
    to_cancel = _book(token, doctor["id"], SLOT_A)
    to_move = _book(token, doctor["id"], SLOT_B)
    hold = _hold(token, doctor["id"], SLOT_C)
    assert hold.status_code == 201, hold.text
    gcal.fail = True

    cancelled = client.post(
        f"/api/appointments/{to_cancel['id']}/cancel",
        json={"reason": "Cannot attend"},
        headers=_auth_header(token),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    moved = client.post(
        f"/api/appointments/{to_move['id']}/reschedule",
        json={"hold_id": hold.json()["id"]},
        headers=_auth_header(token),
    )
    assert moved.status_code == 201, moved.text
    assert moved.json()["status"] == "confirmed"
    db.expire_all()
    cancelled_row = db.get(Appointment, to_cancel["id"])
    previous = db.get(Appointment, to_move["id"])
    replacement = db.get(Appointment, moved.json()["id"])
    assert cancelled_row is not None and cancelled_row.status == AppointmentStatus.CANCELLED
    assert previous is not None and previous.status == AppointmentStatus.RESCHEDULED
    assert replacement is not None and replacement.status == AppointmentStatus.CONFIRMED
    failed = list(
        db.scalars(
            select(CalendarEvent).where(
                CalendarEvent.appointment_id.in_(
                    [to_cancel["id"], to_move["id"], moved.json()["id"]]
                ),
                CalendarEvent.sync_status == CalendarSyncStatus.FAILED,
            )
        )
    )
    assert failed


def test_email_failure_does_not_undo_cancel_or_reschedule(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    mail: _FakeEmail,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    to_cancel = _book(token, doctor["id"], SLOT_A)
    to_move = _book(token, doctor["id"], SLOT_B)
    hold = _hold(token, doctor["id"], SLOT_C)
    assert hold.status_code == 201, hold.text
    mail.calls.clear()
    mail.fail = True

    cancelled = client.post(
        f"/api/appointments/{to_cancel['id']}/cancel",
        json={"reason": "Cannot attend"},
        headers=_auth_header(token),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    moved = client.post(
        f"/api/appointments/{to_move['id']}/reschedule",
        json={"hold_id": hold.json()["id"]},
        headers=_auth_header(token),
    )
    assert moved.status_code == 201, moved.text
    assert moved.json()["status"] == "confirmed"
    db.expire_all()
    cancelled_row = db.get(Appointment, to_cancel["id"])
    previous = db.get(Appointment, to_move["id"])
    replacement = db.get(Appointment, moved.json()["id"])
    assert cancelled_row is not None and cancelled_row.status == AppointmentStatus.CANCELLED
    assert previous is not None and previous.status == AppointmentStatus.RESCHEDULED
    assert replacement is not None and replacement.status == AppointmentStatus.CONFIRMED
    retrying = list(
        db.scalars(
            select(NotificationLog).where(
                NotificationLog.appointment_id.in_([to_cancel["id"], moved.json()["id"]]),
                NotificationLog.status.in_(
                    [NotificationStatus.RETRYING, NotificationStatus.FAILED]
                ),
            )
        )
    )
    assert retrying
    assert mail.calls == []
