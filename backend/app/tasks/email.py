"""Celery email send and retry tasks."""

from app.celery_app import celery_app
from app.core.clock import utc_now
from app.db.session import SessionLocal
from app.services.jobs import enqueue_task
from app.services.notifications import (
    deliver_notification,
    list_pending_notification_ids,
    list_retryable_notification_ids,
)


@celery_app.task(name="app.tasks.email.send_email_notification")
def send_email_notification(notification_id: int) -> str:
    db = SessionLocal()
    try:
        return str(deliver_notification(db, notification_id, utc_now()))
    finally:
        db.close()


@celery_app.task(name="app.tasks.email.dispatch_pending_emails")
def dispatch_pending_emails() -> int:
    db = SessionLocal()
    try:
        ids = list_pending_notification_ids(db)
    finally:
        db.close()
    for notification_id in ids:
        enqueue_task(send_email_notification, notification_id)
    return len(ids)


@celery_app.task(name="app.tasks.email.retry_failed_emails")
def retry_failed_emails() -> int:
    db = SessionLocal()
    try:
        ids = list_retryable_notification_ids(db, utc_now())
    finally:
        db.close()
    for notification_id in ids:
        enqueue_task(send_email_notification, notification_id)
    return len(ids)
