"""Celery calendar sync and failed-integration retry tasks."""

from app.celery_app import celery_app
from app.core.clock import utc_now
from app.db.session import SessionLocal
from app.services.calendar_sync import (
    list_pending_calendar_event_ids,
    list_retryable_calendar_event_ids,
    sync_calendar_event as run_sync_calendar_event,
)
from app.services.jobs import enqueue_task
from app.services.notifications import list_retryable_notification_ids
from app.tasks.email import send_email_notification


@celery_app.task(name="app.tasks.calendar.sync_calendar_event")
def sync_calendar_event(event_id: int) -> str:
    db = SessionLocal()
    try:
        return run_sync_calendar_event(db, event_id, utc_now())
    finally:
        db.close()


@celery_app.task(name="app.tasks.calendar.dispatch_calendar_sync")
def dispatch_calendar_sync() -> int:
    db = SessionLocal()
    try:
        ids = list_pending_calendar_event_ids(db)
    finally:
        db.close()
    for event_id in ids:
        enqueue_task(sync_calendar_event, event_id)
    return len(ids)


@celery_app.task(name="app.tasks.calendar.retry_failed_integrations")
def retry_failed_integrations() -> dict[str, int]:
    db = SessionLocal()
    try:
        calendar_ids = list_retryable_calendar_event_ids(db)
        email_ids = list_retryable_notification_ids(db, utc_now())
    finally:
        db.close()
    for event_id in calendar_ids:
        enqueue_task(sync_calendar_event, event_id)
    for notification_id in email_ids:
        enqueue_task(send_email_notification, notification_id)
    return {"calendar": len(calendar_ids), "email": len(email_ids)}
