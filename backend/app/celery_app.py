"""Celery application. Broker and backend are Redis."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "careconnect",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.email",
        "app.tasks.reminders",
        "app.tasks.calendar",
    ],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=60,
    task_ignore_result=True,
    broker_connection_retry=False,
    broker_connection_retry_on_startup=False,
    broker_connection_timeout=1,
    redis_socket_connect_timeout=1,
    redis_socket_timeout=1,
    redis_retry_on_timeout=False,
    task_annotations={"*": {"max_retries": settings.NOTIFICATION_MAX_RETRIES}},
    beat_schedule={
        "dispatch-appointment-reminders": {
            "task": "app.tasks.reminders.dispatch_appointment_reminders",
            "schedule": crontab(minute="*/15"),
        },
        "dispatch-medication-reminders": {
            "task": "app.tasks.reminders.dispatch_medication_reminders",
            "schedule": crontab(minute="*/10"),
        },
        "dispatch-pending-emails": {
            "task": "app.tasks.email.dispatch_pending_emails",
            "schedule": crontab(minute="*"),
        },
        "retry-failed-emails": {
            "task": "app.tasks.email.retry_failed_emails",
            "schedule": crontab(minute="*/5"),
        },
        "dispatch-calendar-sync": {
            "task": "app.tasks.calendar.dispatch_calendar_sync",
            "schedule": crontab(minute="*/5"),
        },
        "retry-failed-integrations": {
            "task": "app.tasks.calendar.retry_failed_integrations",
            "schedule": crontab(minute="*/10"),
        },
    },
)
