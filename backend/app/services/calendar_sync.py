"""Idempotent Google Calendar sync records and provider calls."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.integrations.calendar import CalendarError, get_calendar_client
from app.integrations.google_oauth import refresh_access_token
from app.models import Appointment, CalendarEvent, CalendarIntegration
from app.models.doctor import DoctorProfile
from app.models.enums import AppointmentStatus, CalendarSyncStatus
from app.models.user import PatientProfile


def record_appointment_calendar_events(db: Session, appointment_id: int) -> list[int]:
    appointment = _load_appointment(db, appointment_id)
    if appointment is None:
        return []
    user_ids = [appointment.patient.user_id, appointment.doctor.user_id]
    event_ids: list[int] = []
    for user_id in user_ids:
        integration = db.scalar(
            select(CalendarIntegration).where(
                CalendarIntegration.user_id == user_id,
                CalendarIntegration.is_connected.is_(True),
            )
        )
        if integration is None:
            continue
        existing = db.scalar(
            select(CalendarEvent).where(
                CalendarEvent.appointment_id == appointment.id,
                CalendarEvent.user_id == user_id,
            )
        )
        if existing is not None:
            event_ids.append(existing.id)
            continue
        event = CalendarEvent(
            appointment_id=appointment.id,
            user_id=user_id,
            calendar_integration_id=integration.id,
            sync_status=CalendarSyncStatus.PENDING,
        )
        db.add(event)
        db.flush()
        event_ids.append(event.id)
    return event_ids


def mark_calendar_events_deleted(db: Session, appointment_id: int) -> list[int]:
    events = list(
        db.scalars(select(CalendarEvent).where(CalendarEvent.appointment_id == appointment_id))
    )
    ids: list[int] = []
    for event in events:
        if event.sync_status == CalendarSyncStatus.DELETED:
            continue
        event.sync_status = CalendarSyncStatus.PENDING
        event.last_error = None
        ids.append(event.id)
    return ids


def rebind_calendar_events_after_reschedule(
    db: Session,
    previous_appointment_id: int,
    appointment_id: int,
) -> list[int]:
    previous_events = list(
        db.scalars(
            select(CalendarEvent).where(CalendarEvent.appointment_id == previous_appointment_id)
        )
    )
    rebound_ids: list[int] = []
    for previous in previous_events:
        provider_event_id = previous.provider_event_id
        previous.provider_event_id = None
        previous.sync_status = CalendarSyncStatus.DELETED
        previous.last_error = None
        db.flush()
        existing = db.scalar(
            select(CalendarEvent).where(
                CalendarEvent.appointment_id == appointment_id,
                CalendarEvent.user_id == previous.user_id,
            )
        )
        if existing is None:
            existing = CalendarEvent(
                appointment_id=appointment_id,
                user_id=previous.user_id,
                calendar_integration_id=previous.calendar_integration_id,
                provider_event_id=provider_event_id,
                sync_status=CalendarSyncStatus.PENDING,
            )
            db.add(existing)
            db.flush()
        else:
            existing.provider_event_id = provider_event_id or existing.provider_event_id
            existing.sync_status = CalendarSyncStatus.PENDING
            existing.last_error = None
        rebound_ids.append(existing.id)
    extra_ids = record_appointment_calendar_events(db, appointment_id)
    return list(dict.fromkeys([*rebound_ids, *extra_ids]))


def enqueue_calendar_deletes(db: Session, appointment_ids: list[int]) -> None:
    from app.services.jobs import enqueue_task
    from app.tasks.calendar import sync_calendar_event

    event_ids: list[int] = []
    for appointment_id in appointment_ids:
        event_ids.extend(mark_calendar_events_deleted(db, appointment_id))
    db.commit()
    for event_id in event_ids:
        enqueue_task(sync_calendar_event, event_id)


def _refresh_integration(integration: CalendarIntegration, now: datetime) -> None:
    tokens = refresh_access_token(
        access_token=integration.access_token,
        refresh_token=integration.refresh_token,
        expiry=integration.token_expiry,
        now=now,
    )
    integration.access_token = tokens.access_token
    integration.refresh_token = tokens.refresh_token
    if tokens.expiry is not None:
        integration.token_expiry = tokens.expiry


def sync_calendar_event(db: Session, event_id: int, now: datetime) -> str:
    event = db.scalar(
        select(CalendarEvent)
        .where(CalendarEvent.id == event_id)
        .options(
            selectinload(CalendarEvent.appointment),
            selectinload(CalendarEvent.integration),
            selectinload(CalendarEvent.user),
        )
        .with_for_update()
    )
    if event is None:
        return "missing"
    appointment = event.appointment
    integration = event.integration
    if appointment is None or integration is None or not integration.is_connected:
        event.sync_status = CalendarSyncStatus.FAILED
        event.last_error = "Calendar integration is not connected"
        db.commit()
        return "failed"

    cancelled = appointment.status in {
        AppointmentStatus.CANCELLED,
        AppointmentStatus.CANCELLED_LEAVE,
        AppointmentStatus.RESCHEDULED,
    }
    if (
        not cancelled
        and event.sync_status == CalendarSyncStatus.SYNCED
        and event.provider_event_id
    ):
        db.commit()
        return "already-synced"
    try:
        _refresh_integration(integration, now)
        client = get_calendar_client()
        if cancelled:
            if event.provider_event_id:
                client.delete_event(
                    access_token=integration.access_token,
                    refresh_token=integration.refresh_token,
                    calendar_id=integration.google_calendar_id,
                    provider_event_id=event.provider_event_id,
                )
            event.sync_status = CalendarSyncStatus.DELETED
            event.last_error = None
            event.last_synced_at = now
            db.commit()
            return "deleted"
        if not event.provider_event_id:
            event.provider_event_id = _deterministic_provider_event_id(appointment.id, event.user_id)
            db.flush()
        provider_id = client.upsert_event(
            access_token=integration.access_token,
            refresh_token=integration.refresh_token,
            calendar_id=integration.google_calendar_id,
            provider_event_id=event.provider_event_id,
            title=_event_title(appointment),
            start=appointment.start_datetime,
            end=appointment.end_datetime,
            description="CareConnect appointment",
        )
        event.provider_event_id = provider_id
        event.sync_status = CalendarSyncStatus.SYNCED
        event.last_error = None
        event.last_synced_at = now
        db.commit()
        return "synced"
    except (CalendarError, Exception) as exc:
        event.sync_status = CalendarSyncStatus.FAILED
        event.last_error = str(exc)[:2000] or "Calendar sync failed"
        db.commit()
        return "failed"


def list_pending_calendar_event_ids(db: Session) -> list[int]:
    return list(
        db.scalars(
            select(CalendarEvent.id).where(CalendarEvent.sync_status == CalendarSyncStatus.PENDING)
        )
    )


def list_retryable_calendar_event_ids(db: Session) -> list[int]:
    return list(
        db.scalars(
            select(CalendarEvent.id).where(CalendarEvent.sync_status == CalendarSyncStatus.FAILED)
        )
    )


def _deterministic_provider_event_id(appointment_id: int, user_id: int) -> str:
    return f"cc{appointment_id:08x}u{user_id:08x}"


def _event_title(appointment: Appointment) -> str:
    return f"{settings.APP_NAME} appointment"


def _load_appointment(db: Session, appointment_id: int) -> Appointment | None:
    return db.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .options(
            selectinload(Appointment.patient).selectinload(PatientProfile.user),
            selectinload(Appointment.doctor).selectinload(DoctorProfile.user),
        )
    )
