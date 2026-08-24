"""SendGrid email notification tests for booking, reminder, cancel, leave, and reschedule."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.email import EmailError, set_email_client
from app.integrations.sendgrid import SendGridEmailClient
from app.main import app
from app.models import Appointment, NotificationLog
from app.models.enums import AppointmentStatus, NotificationStatus, NotificationType, UserRole
from app.services.auth import create_user_with_role
from app.services.notifications import (
    DeliveryResult,
    deliver_notification,
    get_or_create_notification,
)
from app.services.reminders import dispatch_due_appointment_reminders
from app.tasks.email import send_email_notification

client = TestClient(app)

SLOT_A = {
    "start_datetime": "2026-09-07T09:00:00+00:00",
    "end_datetime": "2026-09-07T09:30:00+00:00",
}
SLOT_B = {
    "start_datetime": "2026-09-07T09:30:00+00:00",
    "end_datetime": "2026-09-07T10:00:00+00:00",
}
SYMPTOMS = "Headache for three days."


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeEmail:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls: list[dict[str, str]] = []

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise EmailError("SendGrid unavailable")
        self.calls.append({"recipient": recipient, "subject": subject, "body": body})


@pytest.fixture()
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_overrides() -> None:
    fake = _FakeEmail()
    set_email_client(fake)
    yield fake
    set_email_client(None)
    app.dependency_overrides.clear()


@pytest.fixture()
def mail(_reset_overrides: _FakeEmail) -> _FakeEmail:
    return _reset_overrides


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
        json={"email": email, "password": "securepass1", "full_name": "Email Patient"},
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
            "full_name": "Dr Email",
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


def _logs(db: Session, appointment_id: int, notification_type: str) -> list[NotificationLog]:
    return list(
        db.scalars(
            select(NotificationLog).where(
                NotificationLog.appointment_id == appointment_id,
                NotificationLog.notification_type == notification_type,
            )
        )
    )


def test_sendgrid_client_sends_through_sendgrid_api() -> None:
    set_email_client(None)
    with (
        patch("app.integrations.sendgrid.settings") as fake_settings,
        patch("app.integrations.sendgrid.SendGridAPIClient") as client_cls,
    ):
        fake_settings.SENDGRID_API_KEY = "sg-test-key"
        fake_settings.SENDGRID_FROM_EMAIL = "careconnect@example.com"
        client_cls.return_value.send.return_value = MagicMock(status_code=202)
        SendGridEmailClient().send(
            recipient="patient@example.com",
            subject="CareConnect appointment confirmed",
            body="Your visit is booked.",
        )
        client_cls.assert_called_once_with("sg-test-key")
        client_cls.return_value.send.assert_called_once()


def test_booking_confirmation_is_sent_after_commit(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    mail: _FakeEmail,
) -> None:
    doctor = _create_doctor(admin_token)
    email, token = _register_patient()
    appointment = _book(token, doctor["id"])
    db.expire_all()
    stored = db.get(Appointment, appointment["id"])
    assert stored is not None
    assert stored.status == AppointmentStatus.CONFIRMED
    logs = _logs(db, appointment["id"], NotificationType.BOOKING_CONFIRMATION)
    assert len(logs) == 1
    assert logs[0].status == NotificationStatus.SENT
    assert logs[0].idempotency_key == f"booking-confirmation:{appointment['id']}"
    assert any("confirmed" in call["subject"].lower() for call in mail.calls)
    assert email in {call["recipient"] for call in mail.calls}


def test_email_failure_does_not_invalidate_appointment(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    set_email_client(_FakeEmail(fail_times=99))
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    appointment = _book(token, doctor["id"])
    assert appointment["status"] == "confirmed"
    db.expire_all()
    stored = db.get(Appointment, appointment["id"])
    assert stored is not None
    assert stored.status == AppointmentStatus.CONFIRMED
    logs = _logs(db, appointment["id"], NotificationType.BOOKING_CONFIRMATION)
    assert len(logs) == 1
    assert logs[0].status in {NotificationStatus.RETRYING, NotificationStatus.FAILED}


def test_appointment_reminder_email(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    mail: _FakeEmail,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    appointment = _book(token, doctor["id"])
    mail.calls.clear()
    ids = dispatch_due_appointment_reminders(db, before_monday_hours)
    assert ids
    for notification_id in ids:
        send_email_notification.apply(args=[notification_id]).get()
    db.expire_all()
    logs = _logs(db, appointment["id"], NotificationType.APPOINTMENT_REMINDER)
    assert len(logs) == 1
    assert logs[0].status == NotificationStatus.SENT
    assert logs[0].idempotency_key == f"appointment-reminder:{appointment['id']}"
    assert any("reminder" in call["subject"].lower() for call in mail.calls)
    dispatch_due_appointment_reminders(db, before_monday_hours)
    db.expire_all()
    count = db.scalar(
        select(func.count())
        .select_from(NotificationLog)
        .where(
            NotificationLog.appointment_id == appointment["id"],
            NotificationLog.notification_type == NotificationType.APPOINTMENT_REMINDER,
        )
    )
    assert count == 1


def test_cancellation_email(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    mail: _FakeEmail,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    appointment = _book(token, doctor["id"])
    mail.calls.clear()
    cancelled = client.post(
        f"/api/appointments/{appointment['id']}/cancel",
        json={"reason": "Cannot attend"},
        headers=_auth_header(token),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    db.expire_all()
    logs = _logs(db, appointment["id"], NotificationType.APPOINTMENT_CANCELLATION)
    assert len(logs) == 1
    assert logs[0].status == NotificationStatus.SENT
    assert any("cancelled" in call["subject"].lower() for call in mail.calls)


def test_doctor_leave_cancellation_email(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    mail: _FakeEmail,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    appointment = _book(token, doctor["id"])
    mail.calls.clear()
    leave = client.post(
        f"/api/admin/doctors/{doctor['id']}/leave",
        json={"start_date": "2026-09-07", "end_date": "2026-09-07", "reason": "Conference"},
        headers=_auth_header(admin_token),
    )
    assert leave.status_code == 201, leave.text
    db.expire_all()
    logs = _logs(db, appointment["id"], NotificationType.DOCTOR_LEAVE_CANCELLATION)
    assert len(logs) == 1
    assert logs[0].status == NotificationStatus.SENT
    assert any("leave" in call["subject"].lower() or "cancelled" in call["subject"].lower() for call in mail.calls)
    persisted = db.get(Appointment, appointment["id"])
    assert persisted is not None
    assert persisted.status == AppointmentStatus.CANCELLED_LEAVE


def test_reschedule_notification_email(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    mail: _FakeEmail,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    appointment = _book(token, doctor["id"], SLOT_A)
    hold = client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor["id"], **SLOT_B},
        headers=_auth_header(token),
    )
    assert hold.status_code == 201, hold.text
    mail.calls.clear()
    moved = client.post(
        f"/api/appointments/{appointment['id']}/reschedule",
        json={"hold_id": hold.json()["id"]},
        headers=_auth_header(token),
    )
    assert moved.status_code == 201, moved.text
    body = moved.json()
    assert body["status"] == "confirmed"
    assert body["rescheduled_from_appointment_id"] == appointment["id"]
    db.expire_all()
    previous = db.get(Appointment, appointment["id"])
    assert previous is not None
    assert previous.status == AppointmentStatus.RESCHEDULED
    logs = _logs(db, body["id"], NotificationType.APPOINTMENT_RESCHEDULED)
    assert len(logs) == 2
    assert {row.status for row in logs} == {NotificationStatus.SENT}
    assert {row.idempotency_key for row in logs} == {
        f"appointment-rescheduled:{appointment['id']}:{body['id']}:patient",
        f"appointment-rescheduled:{appointment['id']}:{body['id']}:doctor",
    }
    recipients = {row.recipient for row in logs}
    assert _email_addr in recipients
    assert doctor["email"] in recipients
    assert len([call for call in mail.calls if "rescheduled" in call["subject"].lower()]) == 2


def test_notification_idempotency_and_bounded_retry(db: Session) -> None:
    email, token = _register_patient()
    user_id = client.get("/api/auth/me", headers=_auth_header(token)).json()["id"]
    key = f"email-idempotency-test-key:{uuid4().hex}"
    first, created = get_or_create_notification(
        db,
        user_id=user_id,
        appointment_id=None,
        notification_type=NotificationType.BOOKING_CONFIRMATION,
        recipient=email,
        subject="CareConnect appointment confirmed",
        idempotency_key=key,
    )
    db.commit()
    assert created is True
    second, created_again = get_or_create_notification(
        db,
        user_id=user_id,
        appointment_id=None,
        notification_type=NotificationType.BOOKING_CONFIRMATION,
        recipient=email,
        subject="CareConnect appointment confirmed",
        idempotency_key=key,
    )
    db.commit()
    assert created_again is False
    assert second.id == first.id

    failing = _FakeEmail(fail_times=99)
    set_email_client(failing)
    now = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    results = [
        deliver_notification(db, first.id, now)
        for _ in range(settings.NOTIFICATION_MAX_RETRIES)
    ]
    assert results[-1] == DeliveryResult.FAILED_MAX
    extra = send_email_notification.apply(args=[first.id]).get()
    assert extra == str(DeliveryResult.FAILED_MAX)
    db.expire_all()
    stored = db.get(NotificationLog, first.id)
    assert stored is not None
    assert stored.retry_count == settings.NOTIFICATION_MAX_RETRIES
    assert stored.status == NotificationStatus.FAILED
