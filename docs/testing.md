# Testing

CareConnect is verified with backend pytest (PostgreSQL), a frontend production build, and a source-tree secrets scan. Frontend route guards are not a substitute for API authorization.

Local install and run steps are in the root `README.md`. This file is the QA matrix.

## How to run

PostgreSQL must be running. Tests use `DATABASE_URL` (local default `postgresql://postgres:postgres@localhost:5432/careconnect`).

```bash
cd backend
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/careconnect"
.\.venv\Scripts\python.exe -m pytest -v
```

```bash
cd frontend
npm run build
```

Celery runs in eager mode during tests (`tests/conftest.py`). Redis is not required for pytest. Google, SendGrid, and Gemini are replaced with fakes; live credentials are never used.

## Coverage map

| Area | What is asserted | Tests |
| --- | --- | --- |
| **Auth — registration** | Public register creates a patient only; `role` in the body is ignored; duplicate email is 409; password is never returned | `tests/test_auth.py` |
| **Auth — login / JWT** | Login returns a bearer token; wrong password and missing/invalid/expired tokens are 401; `/api/auth/me` works with a valid token | `tests/test_auth.py` |
| **Auth — roles** | Patient and doctor cannot call `/api/admin/dashboard` (403); admin can; FastAPI role dependencies raise 403 | `tests/test_auth.py` |
| **Auth — authorization** | JWT `role` claim cannot grant admin access; the database role is authoritative | `tests/test_auth.py::test_jwt_role_claim_does_not_override_database_role` |
| **Doctors — create** | Only admin can create; doctors and patients cannot | `tests/test_admin_doctors.py` |
| **Doctors — working hours** | Start before end; no overlap; replace-by-weekday; slot duration bounds | `tests/test_admin_doctors.py` |
| **Doctors — leave** | Leave can be recorded; overlapping leave is 409 | `tests/test_admin_doctors.py`, `tests/test_leave.py` |
| **Doctors — inactive** | Deactivated doctors have no bookable slots and cannot accept bookings | `tests/test_admin_doctors.py`, `tests/test_availability.py` |
| **Appointments — availability** | Hours, duration, weekends, leave, past times, holds, existing visits | `tests/test_availability.py` |
| **Appointments — hold** | Patient can hold; second hold on the same slot is 409; doctors cannot hold | `tests/test_appointments.py` |
| **Appointments — hold expiration** | Expired holds cannot be confirmed and no longer block the slot | `tests/test_appointments.py`, `tests/test_availability.py` |
| **Appointments — booking** | Hold then confirm creates a confirmed row | `tests/test_appointments.py` |
| **Appointments — cancellation** | Authorized cancel keeps history and frees the slot; unauthorized is 401/403 | `tests/test_appointments.py`, `tests/test_cancel_reschedule.py` |
| **Appointments — rescheduling** | Single transaction (not cancel-then-create); old slot freed; concurrent reschedule is one 201 and one 409 | `tests/test_cancel_reschedule.py` |
| **Concurrency** | Two patients booking the same slot: one 201, one 409, exactly one confirmed row | `tests/test_appointments.py::test_concurrent_booking_same_slot_returns_one_conflict`, `tests/test_appointment_overlap.py` |
| **Leave — existing bookings** | Overlapping pending/confirmed visits become `cancelled_leave` | `tests/test_leave.py` |
| **Leave — notify** | Patient `doctor_leave_cancellation` email is recorded and sent (fake SendGrid) | `tests/test_leave.py`, `tests/test_email.py` |
| **Leave — history** | Rows are not deleted; patients can still GET the appointment | `tests/test_leave.py` |
| **AI — success** | Pre-visit JSON and post-visit patient summary stored | `tests/test_previsit.py`, `tests/test_visit.py` |
| **AI — timeout** | Gemini `TimeoutError` becomes `LLMError`; booking still confirms | `tests/test_previsit.py` |
| **AI — API failure** | `LLMError` marks summary failed; appointment/notes still saved | `tests/test_previsit.py`, `tests/test_visit.py` |
| **AI — malformed** | Non-JSON or invalid urgency/questions fail generation, not booking | `tests/test_previsit.py` |
| **AI — retry** | `/previsit-summary/retry` and `/visit/summary/retry` recover after failure | `tests/test_previsit.py`, `tests/test_visit.py` |
| **AI — app continues** | Confirm and visit submit return success when Gemini is down | same tests |
| **Email — success** | Booking, reminder, cancel, leave, reschedule send through the fake client | `tests/test_email.py`, `tests/test_jobs.py` |
| **Email — failure** | Status `retrying`; appointment is not rolled back | `tests/test_jobs.py`, `tests/test_email.py`, `tests/test_cancel_reschedule.py` |
| **Email — retry / max** | Retry then send; cap at `NOTIFICATION_MAX_RETRIES` then `failed` | `tests/test_jobs.py` |
| **Email — idempotency** | Unique `idempotency_key`; already-sent is a no-op | `tests/test_jobs.py`, `tests/test_email.py` |
| **Calendar — OAuth** | Connect URL; callback stores tokens; status/disconnect never return tokens; missing creds 503 | `tests/test_calendar.py` |
| **Calendar — create / update / delete** | Confirm upserts; reschedule keeps provider event id; cancel/leave delete | `tests/test_calendar.py` |
| **Calendar — API failure** | Event `failed`; appointment still confirmed/cancelled/rescheduled | `tests/test_calendar.py`, `tests/test_cancel_reschedule.py` |
| **Calendar — retry / duplicates** | Failed then synced; unique `(appointment_id, user_id)`; already-synced skips a second upsert | `tests/test_jobs.py` |
| **Security — unauthorized** | Missing token is 401 | `tests/test_auth.py` |
| **Security — wrong role** | Patient/doctor vs admin; doctor cannot hold; only assigned doctor submits visit notes | `tests/test_auth.py`, `tests/test_appointments.py`, `tests/test_visit.py`, `tests/test_admin_doctors.py` |
| **Security — cross-user** | Patient A cannot GET/cancel patient B; doctor B cannot see doctor A | `tests/test_appointments.py`, `tests/test_cancel_reschedule.py` |
| **Security — invalid tokens** | Garbage JWT and expired JWT are 401 | `tests/test_auth.py` |
| **Security — secrets** | `.env` gitignored; example env values empty; no live Google/SendGrid/Gemini key patterns in source; placeholder JWT rejected when `APP_ENV=production` | `tests/test_security.py` |

Booking HTTP 409 responses are mapped in the UI to:

`This slot was just booked by another patient. Please select another slot.`

See `frontend/src/lib/format.js`.

## Audit notes

- Backend pytest is the system of record for API behaviour. Do not skip or weaken assertions to get a green run.
- Google Calendar, SendGrid, and Gemini tests are **mocked**. They prove control flow, persistence, and failure isolation, not the vendor networks.
- Concurrent booking uses two `TestClient` threads against the same FastAPI app and real PostgreSQL exclusion constraints.
- Default `JWT_SECRET_KEY` and local `DATABASE_URL` in `app/core/config.py` are development placeholders. Production must set `JWT_SECRET_KEY` via environment (`APP_ENV=production` refuses the placeholder).
- Frontend `npm run build` must succeed as part of this pass. There is no separate frontend unit-test runner.

## Latest audit (2026-08-24)

| Check | Result |
| --- | --- |
| Backend `pytest -v` | **117 passed** in ~178s (pytest 8.3.4, Python 3.13.2, PostgreSQL `careconnect`) |
| Frontend `npm run build` | **Succeeded** (Vite 6.4.3, 124 modules) |
| Tests weakened to pass | None |
| Product defects found this pass | None remaining after adding Gemini timeout handling, production JWT guard, and the tests listed above |

Warnings: 279 `DeprecationWarning` from `python-jose` (`datetime.utcnow()`). They do not fail the suite. Live Google, SendGrid, and Gemini networks were not called.
