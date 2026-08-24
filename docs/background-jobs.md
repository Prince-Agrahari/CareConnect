# Background jobs

CareConnect uses **Celery** with a **Redis** broker for work that must not block appointment, visit, or leave requests.

Broker: `CELERY_BROKER_URL` (default `redis://localhost:6379/0`)  
Result backend: `CELERY_RESULT_BACKEND`

## Jobs

| Task | Schedule | Responsibility |
| --- | --- | --- |
| `app.tasks.reminders.dispatch_appointment_reminders` | every 15 minutes | Notify patients whose visit starts within `APPOINTMENT_REMINDER_HOURS` (default 24) |
| `app.tasks.reminders.dispatch_medication_reminders` | every 10 minutes | Notify patients whose explicit medication reminder time is due |
| `app.tasks.email.send_email_notification` | on enqueue | Send one `notification_logs` row through SendGrid |
| `app.tasks.email.dispatch_pending_emails` | every minute | Enqueue pending rows |
| `app.tasks.email.retry_failed_emails` | every 5 minutes | Enqueue retryable failed/retrying rows after backoff |
| `app.tasks.calendar.sync_calendar_event` | on enqueue | Create, update, or delete one Google Calendar event |
| `app.tasks.calendar.dispatch_calendar_sync` | every 5 minutes | Enqueue pending calendar rows |
| `app.tasks.calendar.retry_failed_integrations` | every 10 minutes | Retry failed calendar rows and retryable emails |

HTTP handlers enqueue these tasks **after** the core transaction commits. If Redis is down, the database row stays `pending` and Beat picks it up later. Email or calendar failure never rolls back an appointment, prescription, or leave. Delivery, backoff, and idempotency keys are in `docs/notification-failure-handling.md`.

## Idempotency

- `notification_logs.idempotency_key` is unique. Retries reuse the same row; they do not insert duplicates.
- A notification already `sent` is a no-op.
- Appointment reminders use `appointment-reminder:{appointment_id}`.
- Medication reminders use `medication-reminder:{id}:{date}:{HH:MM}`.
- Booking confirmation uses `booking-confirmation:{appointment_id}`.
- Cancellation uses `appointment-cancellation:{appointment_id}`.
- Reschedule uses `appointment-rescheduled:{old_id}:{new_id}:patient` and `appointment-rescheduled:{old_id}:{new_id}:doctor`.
- Doctor leave cancellation uses `leave:{leave_id}:appointment:{appointment_id}:patient:{user_id}`.
- `calendar_events` is unique on `(appointment_id, user_id)`. Provider event IDs are unique per integration when set. A `synced` row is not inserted or sent to Google again; reschedule keeps the same Google event id and updates times.

## Bounded retry

`NOTIFICATION_MAX_RETRIES` (default 5) caps email attempts. Each failure increments `retry_count`, stores `error_message` and `last_attempt_at`, and sets status to `retrying`. After the cap, status is `failed` and further tasks return without sending.

Backoff is `min(3600, NOTIFICATION_RETRY_BASE_SECONDS * 2^(retry_count-1))` seconds (default base 60).

Calendar failures set `sync_status = failed` and `last_error`. `retry_failed_integrations` re-queues those rows. Unique event keys prevent duplicate Google events.

## Medication schedules

Reminders are created only from **explicit** prescription text. The job does not invent times or durations.

Accepted frequency examples:

- `once daily at 08:00`
- `twice daily at 08:00 and 20:00`
- `three times daily at 08:00, 14:00, and 20:00`

Accepted duration examples: `5 days`, `2 weeks`.

`twice daily` or `5 days` without clock times produces **no** reminder rows.

## Abstractions

Jobs call `EmailClient` and `CalendarClient` protocols (`backend/app/integrations/email.py`, `backend/app/integrations/calendar.py`). Production adapters are SendGrid and Google Calendar. Tests inject fakes. Appointment services do not import SendGrid or Google libraries.

## Run locally

Redis must be running.

```bash
cd backend
.\.venv\Scripts\activate
celery -A app.celery_app worker -l info --pool=solo
celery -A app.celery_app beat -l info
```

Windows workers need `--pool=solo`.
