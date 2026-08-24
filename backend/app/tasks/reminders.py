"""Celery appointment and medication reminder dispatchers."""

from app.celery_app import celery_app
from app.core.clock import utc_now
from app.db.session import SessionLocal
from app.services.jobs import enqueue_task
from app.services.reminders import (
    dispatch_due_appointment_reminders,
    dispatch_due_medication_reminders,
)
from app.tasks.email import send_email_notification


@celery_app.task(name="app.tasks.reminders.dispatch_appointment_reminders")
def dispatch_appointment_reminders() -> int:
    db = SessionLocal()
    try:
        ids = dispatch_due_appointment_reminders(db, utc_now())
    finally:
        db.close()
    for notification_id in ids:
        enqueue_task(send_email_notification, notification_id)
    return len(ids)


@celery_app.task(name="app.tasks.reminders.dispatch_medication_reminders")
def dispatch_medication_reminders() -> int:
    db = SessionLocal()
    try:
        ids = dispatch_due_medication_reminders(db, utc_now())
    finally:
        db.close()
    for notification_id in ids:
        enqueue_task(send_email_notification, notification_id)
    return len(ids)
