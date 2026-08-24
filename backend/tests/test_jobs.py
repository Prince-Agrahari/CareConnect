"""Celery background job tests: success, failure, retry, max retry, and idempotency."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.clock import utc_now
from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.calendar import CalendarError, set_calendar_client
from app.integrations.email import EmailError, set_email_client
from app.integrations.llm import set_llm_client
from app.main import app
from app.models import CalendarEvent, CalendarIntegration, MedicationReminder, NotificationLog
from app.models.enums import (
    CalendarProvider,
    CalendarSyncStatus,
    MedicationReminderStatus,
    NotificationStatus,
    UserRole,
)
from app.services.auth import create_user_with_role
from app.services.calendar_sync import record_appointment_calendar_events, sync_calendar_event
from app.services.notifications import (
    DeliveryResult,
    deliver_notification,
    get_or_create_notification,
)
from app.services.reminders import (
    dispatch_due_appointment_reminders,
    dispatch_due_medication_reminders,
    parse_duration_days,
    parse_frequency_times,
)
from app.tasks.email import send_email_notification

client = TestClient(app)

MONDAY_START = "2026-09-07T09:00:00+00:00"
MONDAY_END = "2026-09-07T09:30:00+00:00"
SLOT = {"start_datetime": MONDAY_START, "end_datetime": MONDAY_END}
SYMPTOMS = "Headache for three days."


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeEmail:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls: list[tuple[str, str]] = []

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise EmailError("SendGrid unavailable")
        self.calls.append((recipient, subject))


class _FakeCalendar:
    def __init__(self) -> None:
        self.upserts = 0
        self.deletes = 0
        self.fail = False
        self.event_id = "gcal-event-1"

    def upsert_event(self, **kwargs: object) -> str:
        if self.fail:
            raise CalendarError("Google Calendar unavailable")
        self.upserts += 1
        return self.event_id

    def delete_event(self, **kwargs: object) -> None:
        self.deletes += 1


class _PrevisitLLM:
    def generate(self, prompt: str) -> str:
        return (
            '{"urgency_level":"Low","chief_complaint":"Headache",'
            '"suggested_questions":["Q1","Q2","Q3"]}'
        )


@pytest.fixture()
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_overrides() -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    set_email_client(_FakeEmail())
    set_calendar_client(_FakeCalendar())
    set_llm_client(_PrevisitLLM())
    yield
    set_email_client(None)
    set_calendar_client(None)
    set_llm_client(None)
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
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
    return response.json()["access_token"]


def _register_patient() -> tuple[str, str]:
    email = _email("patient")
    register = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "Job Patient"},
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
            "full_name": "Dr Jobs",
            "specialization": "General Medicine",
            "slot_duration_minutes": 30,
            "working_hours": [{"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00"}],
        },
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 201
    return response.json()


def _book(patient_token: str, doctor_id: int) -> dict:
    hold = client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor_id, **SLOT},
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


def _insert_notification(db: Session, user_id: int, recipient: str) -> NotificationLog:
    row, _created = get_or_create_notification(
        db,
        user_id=user_id,
        appointment_id=None,
        notification_type="booking_confirmation",
        recipient=recipient,
        subject="CareConnect appointment confirmed",
        idempotency_key=f"test-email:{uuid4().hex}",
    )
    db.commit()
    db.refresh(row)
    return row


def test_parse_frequency_requires_explicit_times() -> None:
    times = parse_frequency_times("twice daily at 08:00 and 20:00")
    assert times == [time(8, 0), time(20, 0)]
    assert parse_frequency_times("twice daily") is None
    assert parse_frequency_times("as needed") is None
    assert parse_duration_days("5 days") == 5
    assert parse_duration_days("until review") is None


def test_successful_email_task(db: Session) -> None:
    fake = _FakeEmail()
    set_email_client(fake)
    email, token = _register_patient()
    user_id = client.get("/api/auth/me", headers=_auth_header(token)).json()["id"]
    row = _insert_notification(db, user_id, email)
    result = send_email_notification.apply(args=[row.id]).get()
    assert result == DeliveryResult.SENT
    db.expire_all()
    stored = db.get(NotificationLog, row.id)
    assert stored is not None
    assert stored.status == NotificationStatus.SENT
    assert stored.sent_at is not None
    assert len(fake.calls) == 1


def test_email_task_failure_marks_retrying(db: Session) -> None:
    fake = _FakeEmail(fail_times=1)
    set_email_client(fake)
    email, token = _register_patient()
    user_id = client.get("/api/auth/me", headers=_auth_header(token)).json()["id"]
    row = _insert_notification(db, user_id, email)
    now = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    result = deliver_notification(db, row.id, now)
    assert result == DeliveryResult.RETRY
    db.expire_all()
    stored = db.get(NotificationLog, row.id)
    assert stored is not None
    assert stored.status == NotificationStatus.RETRYING
    assert stored.retry_count == 1
    assert stored.error_message == "SendGrid unavailable"
    assert fake.calls == []


def test_email_retry_then_success(db: Session) -> None:
    fake = _FakeEmail(fail_times=1)
    set_email_client(fake)
    email, token = _register_patient()
    user_id = client.get("/api/auth/me", headers=_auth_header(token)).json()["id"]
    row = _insert_notification(db, user_id, email)
    now = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    assert deliver_notification(db, row.id, now) == DeliveryResult.RETRY
    assert deliver_notification(db, row.id, now + timedelta(minutes=2)) == DeliveryResult.SENT
    db.expire_all()
    stored = db.get(NotificationLog, row.id)
    assert stored is not None
    assert stored.status == NotificationStatus.SENT
    assert stored.retry_count == 1
    assert len(fake.calls) == 1


def test_email_stops_at_maximum_retry(db: Session) -> None:
    fake = _FakeEmail(fail_times=99)
    set_email_client(fake)
    email, token = _register_patient()
    user_id = client.get("/api/auth/me", headers=_auth_header(token)).json()["id"]
    row = _insert_notification(db, user_id, email)
    now = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    results = [
        deliver_notification(db, row.id, now + timedelta(minutes=i))
        for i in range(settings.NOTIFICATION_MAX_RETRIES)
    ]
    assert results[-1] == DeliveryResult.FAILED_MAX
    assert all(item in {DeliveryResult.RETRY, DeliveryResult.FAILED_MAX} for item in results)
    extra = deliver_notification(db, row.id, now + timedelta(hours=2))
    assert extra == DeliveryResult.FAILED_MAX
    db.expire_all()
    stored = db.get(NotificationLog, row.id)
    assert stored is not None
    assert stored.status == NotificationStatus.FAILED
    assert stored.retry_count == settings.NOTIFICATION_MAX_RETRIES
    assert fake.calls == []


def test_duplicate_email_send_is_prevented(db: Session) -> None:
    fake = _FakeEmail()
    set_email_client(fake)
    email, token = _register_patient()
    user_id = client.get("/api/auth/me", headers=_auth_header(token)).json()["id"]
    row = _insert_notification(db, user_id, email)
    now = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    assert deliver_notification(db, row.id, now) == DeliveryResult.SENT
    assert deliver_notification(db, row.id, now) == DeliveryResult.ALREADY_SENT
    assert len(fake.calls) == 1
    first, created = get_or_create_notification(
        db,
        user_id=user_id,
        appointment_id=None,
        notification_type="booking_confirmation",
        recipient=email,
        subject="CareConnect appointment confirmed",
        idempotency_key=row.idempotency_key,
    )
    db.commit()
    assert created is False
    assert first.id == row.id


def test_appointment_reminder_dispatch_is_idempotent(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    appointment = _book(token, doctor["id"])
    first = dispatch_due_appointment_reminders(db, before_monday_hours)
    second = dispatch_due_appointment_reminders(db, before_monday_hours)
    assert first
    db.expire_all()
    count = db.scalar(
        select(func.count())
        .select_from(NotificationLog)
        .where(
            NotificationLog.notification_type == "appointment_reminder",
            NotificationLog.appointment_id == appointment["id"],
        )
    )
    assert count == 1
    assert second == first


def test_visit_does_not_invent_medication_schedule(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, patient_token = _register_patient()
    appointment = _book(patient_token, doctor["id"])
    doctor_login = client.post(
        "/api/auth/login",
        json={"email": doctor["email"], "password": "securepass1"},
    )
    created = client.post(
        f"/api/appointments/{appointment['id']}/visit",
        json={
            "clinical_notes": "Tension headache.",
            "follow_up_instructions": "Return in 2 weeks if symptoms persist.",
            "medications": [
                {
                    "medicine_name": "Ibuprofen",
                    "dosage": "400 mg",
                    "frequency": "twice daily",
                    "duration": "5 days",
                    "instructions": "Take after food",
                }
            ],
        },
        headers=_auth_header(doctor_login.json()["access_token"]),
    )
    assert created.status_code == 201, created.text
    db.expire_all()
    count = db.scalar(
        select(func.count())
        .select_from(MedicationReminder)
        .where(MedicationReminder.patient_id == appointment["patient_id"])
    )
    assert count == 0


def test_explicit_medication_frequency_dispatches_once(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, patient_token = _register_patient()
    appointment = _book(patient_token, doctor["id"])
    doctor_login = client.post(
        "/api/auth/login",
        json={"email": doctor["email"], "password": "securepass1"},
    )
    created = client.post(
        f"/api/appointments/{appointment['id']}/visit",
        json={
            "clinical_notes": "Tension headache.",
            "follow_up_instructions": "Return in 2 weeks if symptoms persist.",
            "medications": [
                {
                    "medicine_name": "Ibuprofen",
                    "dosage": "400 mg",
                    "frequency": "twice daily at 08:00 and 20:00",
                    "duration": "5 days",
                    "instructions": "Take after food",
                }
            ],
        },
        headers=_auth_header(doctor_login.json()["access_token"]),
    )
    assert created.status_code == 201, created.text
    db.expire_all()
    reminders = list(
        db.scalars(
            select(MedicationReminder).where(
                MedicationReminder.patient_id == appointment["patient_id"]
            )
        ).all()
    )
    assert len(reminders) == 2
    morning = next(item for item in reminders if item.remind_at == time(8, 0))
    morning.next_scheduled_at = before_monday_hours
    db.commit()
    first = dispatch_due_medication_reminders(db, before_monday_hours)
    second = dispatch_due_medication_reminders(db, before_monday_hours)
    assert len(first) == 1
    assert second == []
    db.expire_all()
    logs = list(
        db.scalars(
            select(NotificationLog).where(
                NotificationLog.notification_type == "medication_reminder",
                NotificationLog.user_id == client.get(
                    "/api/auth/me", headers=_auth_header(patient_token)
                ).json()["id"],
            )
        )
    )
    assert len(logs) == 1
    updated = db.get(MedicationReminder, morning.id)
    assert updated is not None
    assert updated.next_scheduled_at == before_monday_hours + timedelta(days=1)
    assert updated.status == MedicationReminderStatus.ACTIVE


def test_calendar_sync_success_and_duplicate_prevention(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    fake = _FakeCalendar()
    set_calendar_client(fake)
    doctor = _create_doctor(admin_token)
    email, token = _register_patient()
    appointment = _book(token, doctor["id"])
    me = client.get("/api/auth/me", headers=_auth_header(token)).json()
    db.add(
        CalendarIntegration(
            user_id=me["id"],
            provider=CalendarProvider.GOOGLE,
            access_token="access-token",
            refresh_token="refresh-token",
            is_connected=True,
        )
    )
    db.commit()
    ids = record_appointment_calendar_events(db, appointment["id"])
    db.commit()
    assert len(ids) == 1
    now = before_monday_hours
    assert sync_calendar_event(db, ids[0], now) == "synced"
    assert sync_calendar_event(db, ids[0], now) == "already-synced"
    assert fake.upserts == 1
    db.expire_all()
    event = db.get(CalendarEvent, ids[0])
    assert event is not None
    assert event.sync_status == CalendarSyncStatus.SYNCED
    assert event.provider_event_id == "gcal-event-1"
    again = record_appointment_calendar_events(db, appointment["id"])
    db.commit()
    assert again == ids


def test_failed_calendar_retry(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
) -> None:
    fake = _FakeCalendar()
    fake.fail = True
    set_calendar_client(fake)
    doctor = _create_doctor(admin_token)
    email, token = _register_patient()
    appointment = _book(token, doctor["id"])
    me = client.get("/api/auth/me", headers=_auth_header(token)).json()
    db.add(
        CalendarIntegration(
            user_id=me["id"],
            provider=CalendarProvider.GOOGLE,
            access_token="access-token",
            refresh_token="refresh-token",
            is_connected=True,
        )
    )
    db.commit()
    ids = record_appointment_calendar_events(db, appointment["id"])
    db.commit()
    assert sync_calendar_event(db, ids[0], before_monday_hours) == "failed"
    db.expire_all()
    event = db.get(CalendarEvent, ids[0])
    assert event is not None
    assert event.sync_status == CalendarSyncStatus.FAILED
    fake.fail = False
    assert sync_calendar_event(db, ids[0], before_monday_hours) == "synced"
    db.expire_all()
    event = db.get(CalendarEvent, ids[0])
    assert event is not None
    assert event.sync_status == CalendarSyncStatus.SYNCED
