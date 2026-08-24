# Notification failure handling

Email and Google Calendar run **after** the appointment, leave, or visit transaction commits. A provider outage must not undo a valid booking, cancellation, reschedule, or leave record.

This document covers delivery, retry, and idempotency. Schedules and task names are in `docs/background-jobs.md`.

## Principle

1. Write the clinical/booking row and a `pending` outbox row in PostgreSQL (or enqueue immediately after commit).
2. Return success to the client for the core action.
3. Attempt SendGrid or Google Calendar asynchronously.
4. On failure, keep the core row and retry the outbox row with a cap.

Gemini is separate: it runs in-process after commit and writes `failed` on the summary row. It does not use `notification_logs`. See `docs/llm-prompts.md`.

## Email outbox

Table `notification_logs`:

| Field | Role |
| --- | --- |
| `status` | `pending`, `retrying`, `sent`, `failed` |
| `retry_count` | Incremented on each failed send |
| `error_message` | Last provider error (truncated) |
| `last_attempt_at` | Used for backoff |
| `sent_at` | Set when SendGrid succeeds |
| `idempotency_key` | Unique; retries reuse the same row |
| `channel` | Always `email` in this codebase |
| `recipient` | User email at send time |

HTTP handlers call `get_or_create_notification` then `enqueue_task(send_email_notification, id)`. If Redis is unreachable, `enqueue_task` returns without raising. Beat’s `dispatch_pending_emails` (every minute) picks up leftover `pending` rows.

## Successful send

`deliver_notification` locks the row (`FOR UPDATE`), calls `EmailClient.send`, sets `status = sent`, and stores `sent_at`.

If `SENDGRID_API_KEY` or `SENDGRID_FROM_EMAIL` is missing, the SendGrid adapter raises `EmailError`. That is treated as a failed attempt, not as a rolled-back appointment.

## Failed send

On `EmailError` or any other exception:

1. `retry_count += 1`
2. `error_message` is stored
3. If `retry_count < NOTIFICATION_MAX_RETRIES` (default 5): `status = retrying`
4. Else: `status = failed` and further tasks return `failed_max` without calling SendGrid

Admins can list rows at `GET /api/admin/notifications` (optional `?status=`). The admin UI flags `pending`, `retrying`, and `failed` as needing attention. There is no admin “force resend” endpoint.

## Retry and backoff

Celery beat runs `retry_failed_emails` every five minutes. Rows in `retrying` (and `failed` with `retry_count` still below the cap) are eligible after:

```
wait = min(3600, NOTIFICATION_RETRY_BASE_SECONDS * 2^(retry_count-1))
```

Default base is 60 seconds. Example waits: 60s, 120s, 240s, 480s, then cap at one hour.

## Idempotency

`idempotency_key` is unique. A second insert with the same key returns the existing row.

A row already `sent` is a no-op (`already_sent`). Celery retries and beat dispatch cannot produce a second SendGrid send for that key.

Documented keys:

| Event | Key |
| --- | --- |
| Booking confirmation | `booking-confirmation:{appointment_id}` |
| Appointment reminder | `appointment-reminder:{appointment_id}` |
| Patient cancellation | `appointment-cancellation:{appointment_id}` |
| Reschedule (patient) | `appointment-rescheduled:{old_id}:{new_id}:patient` |
| Reschedule (doctor) | `appointment-rescheduled:{old_id}:{new_id}:doctor` |
| Leave cancellation (patient) | `leave:{leave_id}:appointment:{appointment_id}:patient:{user_id}` |
| Medication reminder | `medication-reminder:{id}:{date}:{HH:MM}` |

## Calendar outbox

Table `calendar_events`, unique on `(appointment_id, user_id)`:

| `sync_status` | Meaning |
| --- | --- |
| `pending` | Not yet sent to Google |
| `synced` | `provider_event_id` stored |
| `failed` | Last API call failed; `last_error` set |
| `deleted` | Event removed at Google (cancel / leave) |

Confirm creates pending rows for the patient and the doctor **only if** that user has a connected Google integration. Reschedule updates the existing event id. Cancel and leave delete remote events.

`retry_failed_integrations` (every 10 minutes) re-queues `failed` rows. A `synced` row is not inserted again and is not created twice at Google. Missing Google credentials or API errors set `failed` and never change appointment status.

Expired Google access tokens are refreshed with the stored refresh token before Calendar API calls. Tokens are never returned to the frontend.

## What Redis downtime looks like

- HTTP confirm still returns 201 if the appointment committed.
- Email/calendar rows stay `pending`.
- When Redis and workers return, beat dispatches them.
- Pytest does not need Redis: `tests/conftest.py` sets Celery `task_always_eager`.

## Tests

- `tests/test_email.py` — send, booking email after commit, failure isolation, reminder/cancel/leave/reschedule bodies, idempotency
- `tests/test_jobs.py` — success, retrying, retry then success, max retry, duplicate send, calendar retry/duplicates
- `tests/test_cancel_reschedule.py` — email/calendar failure does not undo cancel or reschedule
- `tests/test_calendar.py` — OAuth, CRUD, API failure isolation, token refresh
