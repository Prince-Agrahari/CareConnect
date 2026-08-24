"""Mocked Google Calendar OAuth and appointment sync tests. No live Google calls."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
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
from app.integrations.email import set_email_client
from app.integrations.google_oauth import GoogleOAuthTokens, create_oauth_state
from app.main import app
from app.models import Appointment, CalendarEvent, CalendarIntegration
from app.models.enums import AppointmentStatus, CalendarProvider, CalendarSyncStatus, UserRole
from app.services.auth import create_user_with_role
from app.services.calendar_sync import record_appointment_calendar_events, sync_calendar_event

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
    def send(self, *, recipient: str, subject: str, body: str) -> None:
        return None


class _FakeCalendar:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.upserts: list[dict] = []
        self.deletes: list[dict] = []
        self._n = 0

    def upsert_event(self, **kwargs: object) -> str:
        if self.fail:
            raise CalendarError("Google Calendar unavailable")
        self.upserts.append(kwargs)
        existing = kwargs.get("provider_event_id")
        if isinstance(existing, str) and existing:
            return existing
        self._n += 1
        return f"gcal-event-{self._n}"

    def delete_event(self, **kwargs: object) -> None:
        self.deletes.append(kwargs)


@pytest.fixture()
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_overrides() -> _FakeCalendar:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    calendar = _FakeCalendar()
    set_email_client(_FakeEmail())
    set_calendar_client(calendar)
    yield calendar
    set_email_client(None)
    set_calendar_client(None)
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    app.dependency_overrides.clear()


@pytest.fixture()
def gcal(_reset_overrides: _FakeCalendar) -> _FakeCalendar:
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
        json={"email": email, "password": "securepass1", "full_name": "Calendar Patient"},
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
            "full_name": "Dr Calendar",
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


def _connect(db: Session, user_id: int, *, expiry: datetime | None = None) -> CalendarIntegration:
    row = CalendarIntegration(
        user_id=user_id,
        provider=CalendarProvider.GOOGLE,
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=expiry,
        google_calendar_id="primary",
        is_connected=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _events(db: Session, appointment_id: int) -> list[CalendarEvent]:
    return list(
        db.scalars(select(CalendarEvent).where(CalendarEvent.appointment_id == appointment_id))
    )


def test_connect_without_google_credentials_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")
    _, token = _register_patient()
    response = client.get("/api/v1/calendar/connect", headers=_auth_header(token))
    assert response.status_code == 503
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text


def test_connect_returns_authorization_url_without_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.calendar_oauth.build_authorization_url",
        lambda state: "https://accounts.google.com/o/oauth2/auth?mock=1",
    )
    _, token = _register_patient()
    response = client.get("/api/v1/calendar/connect", headers=_auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/")
    assert body["provider"] == "google"
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text


def test_oauth_callback_stores_tokens_and_status_hides_them(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_SUCCESS_REDIRECT", "http://localhost:5173/?calendar=connected")
    _, token = _register_patient()
    me = client.get("/api/auth/me", headers=_auth_header(token)).json()
    expiry = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    tokens = GoogleOAuthTokens(
        access_token="oauth-access-secret",
        refresh_token="oauth-refresh-secret",
        expiry=expiry,
        scopes="https://www.googleapis.com/auth/calendar.events",
    )
    state = create_oauth_state(me["id"])
    with patch(
        "app.services.calendar_oauth.exchange_authorization_code",
        return_value=tokens,
    ):
        response = client.get(
            "/api/v1/calendar/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    location = response.headers.get("location", "")
    assert "calendar=connected" in location
    assert "oauth-access-secret" not in location
    assert "oauth-refresh-secret" not in location
    assert "oauth-access-secret" not in response.text
    db.expire_all()
    stored = db.scalar(
        select(CalendarIntegration).where(CalendarIntegration.user_id == me["id"])
    )
    assert stored is not None
    assert stored.is_connected is True
    assert stored.access_token == "oauth-access-secret"
    assert stored.refresh_token == "oauth-refresh-secret"
    status = client.get("/api/v1/calendar/status", headers=_auth_header(token))
    assert status.status_code == 200
    body = status.json()
    assert body["connected"] is True
    assert body["provider"] == "google"
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "oauth-access-secret" not in status.text
    assert "oauth-refresh-secret" not in status.text


def test_disconnect_clears_connection(db: Session) -> None:
    _, token = _register_patient()
    me = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, me["id"])
    disconnected = client.post("/api/v1/calendar/disconnect", headers=_auth_header(token))
    assert disconnected.status_code == 200
    body = disconnected.json()
    assert body["connected"] is False
    assert "access_token" not in body
    status = client.get("/api/v1/calendar/status", headers=_auth_header(token))
    assert status.json()["connected"] is False
    db.expire_all()
    stored = db.scalar(
        select(CalendarIntegration).where(CalendarIntegration.user_id == me["id"])
    )
    assert stored is not None
    assert stored.is_connected is False
    assert stored.access_token == ""
    assert stored.refresh_token == ""


def test_confirm_creates_events_for_patient_and_doctor(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    gcal: _FakeCalendar,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, patient["id"])
    _connect(db, doctor["user_id"])
    appointment = _book(token, doctor["id"])
    db.expire_all()
    events = _events(db, appointment["id"])
    assert len(events) == 2
    assert {event.user_id for event in events} == {patient["id"], doctor["user_id"]}
    assert all(event.sync_status == CalendarSyncStatus.SYNCED for event in events)
    assert all(event.provider_event_id for event in events)
    assert all(event.last_synced_at is not None for event in events)
    assert all(event.last_error is None for event in events)
    assert len(gcal.upserts) == 2
    again = record_appointment_calendar_events(db, appointment["id"])
    db.commit()
    assert set(again) == {event.id for event in events}
    count = db.scalar(
        select(func.count())
        .select_from(CalendarEvent)
        .where(CalendarEvent.appointment_id == appointment["id"])
    )
    assert count == 2


def test_reschedule_updates_existing_google_events(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    gcal: _FakeCalendar,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, patient["id"])
    appointment = _book(token, doctor["id"], SLOT_A)
    db.expire_all()
    original = _events(db, appointment["id"])
    assert len(original) == 1
    original_provider_id = original[0].provider_event_id
    assert original_provider_id
    hold = client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor["id"], **SLOT_B},
        headers=_auth_header(token),
    )
    assert hold.status_code == 201, hold.text
    moved = client.post(
        f"/api/appointments/{appointment['id']}/reschedule",
        json={"hold_id": hold.json()["id"]},
        headers=_auth_header(token),
    )
    assert moved.status_code == 201, moved.text
    new_id = moved.json()["id"]
    db.expire_all()
    previous_events = _events(db, appointment["id"])
    assert all(event.sync_status == CalendarSyncStatus.DELETED for event in previous_events)
    assert all(event.provider_event_id is None for event in previous_events)
    new_events = _events(db, new_id)
    assert len(new_events) == 1
    assert new_events[0].provider_event_id == original_provider_id
    assert new_events[0].sync_status == CalendarSyncStatus.SYNCED
    assert any(call.get("provider_event_id") == original_provider_id for call in gcal.upserts)
    last_upsert = gcal.upserts[-1]
    assert last_upsert["provider_event_id"] == original_provider_id
    assert last_upsert["start"] == datetime.fromisoformat(SLOT_B["start_datetime"])
    assert last_upsert["end"] == datetime.fromisoformat(SLOT_B["end_datetime"])


def test_cancel_deletes_calendar_events(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    gcal: _FakeCalendar,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, patient["id"])
    appointment = _book(token, doctor["id"])
    db.expire_all()
    provider_id = _events(db, appointment["id"])[0].provider_event_id
    cancelled = client.post(
        f"/api/appointments/{appointment['id']}/cancel",
        json={"reason": "Cannot attend"},
        headers=_auth_header(token),
    )
    assert cancelled.status_code == 200
    db.expire_all()
    events = _events(db, appointment["id"])
    assert len(events) == 1
    assert events[0].sync_status == CalendarSyncStatus.DELETED
    assert len(gcal.deletes) == 1
    assert gcal.deletes[0]["provider_event_id"] == provider_id


def test_doctor_leave_deletes_calendar_events(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    gcal: _FakeCalendar,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, patient["id"])
    appointment = _book(token, doctor["id"])
    leave = client.post(
        f"/api/admin/doctors/{doctor['id']}/leave",
        json={"start_date": "2026-09-07", "end_date": "2026-09-07", "reason": "Conference"},
        headers=_auth_header(admin_token),
    )
    assert leave.status_code == 201, leave.text
    db.expire_all()
    persisted = db.get(Appointment, appointment["id"])
    assert persisted is not None
    assert persisted.status == AppointmentStatus.CANCELLED_LEAVE
    events = _events(db, appointment["id"])
    assert len(events) == 1
    assert events[0].sync_status == CalendarSyncStatus.DELETED
    assert len(gcal.deletes) == 1


def test_calendar_failure_does_not_roll_back_appointment(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    gcal: _FakeCalendar,
) -> None:
    gcal.fail = True
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    _connect(db, patient["id"])
    appointment = _book(token, doctor["id"])
    assert appointment["status"] == "confirmed"
    db.expire_all()
    stored = db.get(Appointment, appointment["id"])
    assert stored is not None
    assert stored.status == AppointmentStatus.CONFIRMED
    events = _events(db, appointment["id"])
    assert len(events) == 1
    assert events[0].sync_status == CalendarSyncStatus.FAILED
    assert events[0].last_error
    gcal.fail = False
    assert sync_calendar_event(db, events[0].id, before_monday_hours) == "synced"
    db.expire_all()
    retried = db.get(CalendarEvent, events[0].id)
    assert retried is not None
    assert retried.sync_status == CalendarSyncStatus.SYNCED
    assert retried.provider_event_id
    assert len(gcal.upserts) == 1


def test_expired_access_token_is_refreshed_before_sync(
    admin_token: str,
    db: Session,
    before_monday_hours: datetime,
    gcal: _FakeCalendar,
) -> None:
    doctor = _create_doctor(admin_token)
    _email_addr, token = _register_patient()
    patient = client.get("/api/auth/me", headers=_auth_header(token)).json()
    appointment = _book(token, doctor["id"])
    integration = _connect(
        db,
        patient["id"],
        expiry=before_monday_hours - timedelta(minutes=5),
    )
    ids = record_appointment_calendar_events(db, appointment["id"])
    db.commit()
    assert len(ids) == 1
    rotated_expiry = before_monday_hours + timedelta(hours=1)
    with patch("app.services.calendar_sync.refresh_access_token") as mocked:
        mocked.return_value = GoogleOAuthTokens(
            access_token="rotated-access",
            refresh_token="rotated-refresh",
            expiry=rotated_expiry,
            scopes=None,
        )
        assert sync_calendar_event(db, ids[0], before_monday_hours) == "synced"
        mocked.assert_called_once()
    db.expire_all()
    stored = db.get(CalendarIntegration, integration.id)
    assert stored is not None
    assert stored.access_token == "rotated-access"
    assert stored.refresh_token == "rotated-refresh"
    assert stored.token_expiry == rotated_expiry
    assert gcal.upserts[0]["access_token"] == "rotated-access"
