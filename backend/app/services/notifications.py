"""Notification persistence, idempotent enqueue, and bounded email delivery."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.integrations.email import EmailError, get_email_client
from app.models import Appointment, NotificationLog
from app.models.doctor import DoctorProfile
from app.models.enums import NotificationChannel, NotificationStatus, NotificationType
from app.models.user import PatientProfile


class DeliveryResult(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    RETRY = "retry"
    FAILED_MAX = "failed_max"
    SKIPPED = "skipped"


def retry_backoff_seconds(retry_count: int) -> int:
    exponent = max(retry_count - 1, 0)
    return min(3600, settings.NOTIFICATION_RETRY_BASE_SECONDS * (2**exponent))


def get_or_create_notification(
    db: Session,
    *,
    user_id: int,
    appointment_id: int | None,
    notification_type: str,
    recipient: str,
    subject: str,
    idempotency_key: str,
) -> tuple[NotificationLog, bool]:
    existing = db.scalar(
        select(NotificationLog).where(NotificationLog.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing, False
    row = NotificationLog(
        user_id=user_id,
        appointment_id=appointment_id,
        notification_type=notification_type,
        channel=NotificationChannel.EMAIL,
        recipient=recipient,
        subject=subject,
        status=NotificationStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    db.add(row)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(NotificationLog).where(NotificationLog.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        return existing, False
    return row, True


def render_email_body(db: Session, notification: NotificationLog) -> str:
    kind = notification.notification_type
    if kind == NotificationType.BOOKING_CONFIRMATION:
        appointment = _appointment(db, notification.appointment_id)
        when = appointment.start_datetime.isoformat() if appointment else "your scheduled time"
        return (
            f"Your CareConnect appointment is confirmed for {when}.\n\n"
            "This message is a booking confirmation, not medical advice."
        )
    if kind == NotificationType.APPOINTMENT_REMINDER:
        appointment = _appointment(db, notification.appointment_id)
        when = appointment.start_datetime.isoformat() if appointment else "your scheduled time"
        return f"Reminder: you have a CareConnect appointment at {when}."
    if kind == NotificationType.APPOINTMENT_CANCELLATION:
        return "Your CareConnect appointment was cancelled."
    if kind == NotificationType.DOCTOR_LEAVE_CANCELLATION:
        return "Your CareConnect appointment was cancelled because the doctor is on leave."
    if kind == NotificationType.DOCTOR_LEAVE_PROCESSED:
        return "Your leave was recorded in CareConnect. Affected patients have been notified."
    if kind == NotificationType.APPOINTMENT_RESCHEDULED:
        appointment = _appointment(db, notification.appointment_id)
        when = appointment.start_datetime.isoformat() if appointment else "your new time"
        return (
            f"Your CareConnect appointment was rescheduled. "
            f"The new time is {when}."
        )
    if kind == NotificationType.MEDICATION_REMINDER:
        return (
            f"{notification.subject}\n\n"
            "Take this medication exactly as prescribed. This reminder uses the frequency "
            "entered by your doctor and does not change your prescription."
        )
    return notification.subject


def _appointment(db: Session, appointment_id: int | None) -> Appointment | None:
    if appointment_id is None:
        return None
    return db.get(Appointment, appointment_id)


def deliver_notification(db: Session, notification_id: int, now: datetime) -> DeliveryResult:
    notification = db.scalar(
        select(NotificationLog)
        .where(NotificationLog.id == notification_id)
        .with_for_update()
    )
    if notification is None:
        return DeliveryResult.SKIPPED
    if notification.status == NotificationStatus.SENT:
        return DeliveryResult.ALREADY_SENT
    if (
        notification.retry_count >= settings.NOTIFICATION_MAX_RETRIES
        and notification.status == NotificationStatus.FAILED
    ):
        return DeliveryResult.FAILED_MAX

    body = render_email_body(db, notification)
    notification.last_attempt_at = now
    try:
        get_email_client().send(
            recipient=notification.recipient,
            subject=notification.subject,
            body=body,
        )
        notification.status = NotificationStatus.SENT
        notification.sent_at = now
        notification.error_message = None
        db.commit()
        return DeliveryResult.SENT
    except (EmailError, Exception) as exc:
        notification.retry_count += 1
        notification.error_message = str(exc)[:2000] or "Email delivery failed"
        if notification.retry_count >= settings.NOTIFICATION_MAX_RETRIES:
            notification.status = NotificationStatus.FAILED
            db.commit()
            return DeliveryResult.FAILED_MAX
        notification.status = NotificationStatus.RETRYING
        db.commit()
        return DeliveryResult.RETRY


def list_pending_notification_ids(db: Session) -> list[int]:
    rows = db.scalars(
        select(NotificationLog.id).where(NotificationLog.status == NotificationStatus.PENDING)
    )
    return list(rows)


def list_retryable_notification_ids(db: Session, now: datetime) -> list[int]:
    rows = db.scalars(
        select(NotificationLog).where(
            NotificationLog.status.in_([NotificationStatus.RETRYING, NotificationStatus.FAILED]),
            NotificationLog.retry_count < settings.NOTIFICATION_MAX_RETRIES,
        )
    )
    ready: list[int] = []
    for row in rows:
        if row.last_attempt_at is None:
            ready.append(row.id)
            continue
        wait = timedelta(seconds=retry_backoff_seconds(row.retry_count))
        if row.last_attempt_at + wait <= now:
            ready.append(row.id)
    return ready


def record_booking_confirmation(db: Session, appointment_id: int) -> NotificationLog | None:
    appointment = _load_appointment_users(db, appointment_id)
    if appointment is None:
        return None
    patient_user = appointment.patient.user
    row, _created = get_or_create_notification(
        db,
        user_id=patient_user.id,
        appointment_id=appointment.id,
        notification_type=NotificationType.BOOKING_CONFIRMATION,
        recipient=patient_user.email,
        subject="CareConnect appointment confirmed",
        idempotency_key=f"booking-confirmation:{appointment.id}",
    )
    return row


def record_appointment_cancellation(db: Session, appointment_id: int) -> NotificationLog | None:
    appointment = _load_appointment_users(db, appointment_id)
    if appointment is None:
        return None
    patient_user = appointment.patient.user
    row, _created = get_or_create_notification(
        db,
        user_id=patient_user.id,
        appointment_id=appointment.id,
        notification_type=NotificationType.APPOINTMENT_CANCELLATION,
        recipient=patient_user.email,
        subject="CareConnect appointment cancelled",
        idempotency_key=f"appointment-cancellation:{appointment.id}",
    )
    return row


def record_appointment_reminder(db: Session, appointment_id: int) -> tuple[NotificationLog, bool]:
    appointment = _load_appointment_users(db, appointment_id)
    if appointment is None:
        raise ValueError("appointment not found")
    patient_user = appointment.patient.user
    return get_or_create_notification(
        db,
        user_id=patient_user.id,
        appointment_id=appointment.id,
        notification_type=NotificationType.APPOINTMENT_REMINDER,
        recipient=patient_user.email,
        subject="CareConnect appointment reminder",
        idempotency_key=f"appointment-reminder:{appointment.id}",
    )


def after_appointment_confirmed(db: Session, appointment_id: int) -> None:
    from app.services.calendar_sync import record_appointment_calendar_events
    from app.services.jobs import enqueue_task
    from app.tasks.calendar import sync_calendar_event
    from app.tasks.email import send_email_notification

    notification = record_booking_confirmation(db, appointment_id)
    event_ids = record_appointment_calendar_events(db, appointment_id)
    db.commit()
    if notification is not None:
        enqueue_task(send_email_notification, notification.id)
    for event_id in event_ids:
        enqueue_task(sync_calendar_event, event_id)


def after_appointment_cancelled(db: Session, appointment_id: int) -> None:
    from app.services.calendar_sync import mark_calendar_events_deleted
    from app.services.jobs import enqueue_task
    from app.tasks.calendar import sync_calendar_event
    from app.tasks.email import send_email_notification

    notification = record_appointment_cancellation(db, appointment_id)
    event_ids = mark_calendar_events_deleted(db, appointment_id)
    db.commit()
    if notification is not None:
        enqueue_task(send_email_notification, notification.id)
    for event_id in event_ids:
        enqueue_task(sync_calendar_event, event_id)


def record_appointment_rescheduled(
    db: Session,
    previous_appointment_id: int,
    appointment_id: int,
) -> list[NotificationLog]:
    appointment = _load_appointment_users(db, appointment_id)
    if appointment is None:
        return []
    patient_user = appointment.patient.user
    doctor_user = appointment.doctor.user
    logs: list[NotificationLog] = []
    for user, audience in ((patient_user, "patient"), (doctor_user, "doctor")):
        row, _created = get_or_create_notification(
            db,
            user_id=user.id,
            appointment_id=appointment.id,
            notification_type=NotificationType.APPOINTMENT_RESCHEDULED,
            recipient=user.email,
            subject="CareConnect appointment rescheduled",
            idempotency_key=(
                f"appointment-rescheduled:{previous_appointment_id}:{appointment.id}:{audience}"
            ),
        )
        logs.append(row)
    return logs


def after_appointment_rescheduled(
    db: Session,
    previous_appointment_id: int,
    appointment_id: int,
) -> None:
    from app.services.calendar_sync import rebind_calendar_events_after_reschedule
    from app.services.jobs import enqueue_task
    from app.tasks.calendar import sync_calendar_event
    from app.tasks.email import send_email_notification

    notifications = record_appointment_rescheduled(db, previous_appointment_id, appointment_id)
    event_ids = rebind_calendar_events_after_reschedule(db, previous_appointment_id, appointment_id)
    db.commit()
    for notification in notifications:
        enqueue_task(send_email_notification, notification.id)
    for event_id in event_ids:
        enqueue_task(sync_calendar_event, event_id)


def enqueue_pending_notification_sends(db: Session) -> int:
    from app.services.jobs import enqueue_task
    from app.tasks.email import send_email_notification

    ids = list_pending_notification_ids(db)
    for notification_id in ids:
        enqueue_task(send_email_notification, notification_id)
    return len(ids)


def _load_appointment_users(db: Session, appointment_id: int) -> Appointment | None:
    return db.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .options(
            selectinload(Appointment.patient).selectinload(PatientProfile.user),
            selectinload(Appointment.doctor).selectinload(DoctorProfile.user),
        )
    )


def list_notification_logs(db: Session, *, status: str | None = None, limit: int = 200) -> list[NotificationLog]:
    query = select(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(limit)
    if status:
        query = query.where(NotificationLog.status == status)
    return list(db.scalars(query).all())


def queue_leave_notification_sends() -> None:
    from app.services.jobs import enqueue_task
    from app.tasks.email import dispatch_pending_emails

    enqueue_task(dispatch_pending_emails)
