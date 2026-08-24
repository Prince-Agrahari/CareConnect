# API documentation

Interactive OpenAPI is served by FastAPI:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Schema: `http://localhost:8000/openapi.json`

Login is JSON (`POST /api/auth/login`), not OAuth2 form-urlencoded. In Swagger, log in with a REST client (or the UI), copy `access_token`, and authorize with **Bearer**. The `tokenUrl` on `OAuth2PasswordBearer` does not match the JSON body.

Unless noted, send `Authorization: Bearer <access_token>` and `Content-Type: application/json`.

Role is taken from `users.role` in PostgreSQL after the token `sub` is loaded. A forged JWT `role` claim does not grant admin access.

## Health

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | none | Liveness. `{ status, service, message }` |
| GET | `/api/v1/health` | none | Liveness. `{ status, service, environment }` |
| GET | `/api/v1/health/db` | none | Executes `SELECT 1`. `{ status, database }` (`connected` or `disconnected`) |

## Auth

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | none | Creates a **patient** only. Extra fields including `role` are ignored. Password min length 8. Duplicate email → 409. Password is never returned. |
| POST | `/api/auth/login` | none | `{ email, password }` → `{ access_token, token_type: "bearer", user }`. Wrong password or inactive user → 401. |
| GET | `/api/auth/me` | any user | Current user from the database. |

Register body:

```json
{
  "email": "patient@example.com",
  "password": "at-least-8-characters",
  "full_name": "Alex Patient"
}
```

`UserPublic`: `id`, `email`, `full_name`, `role`, `is_active`.

Default token lifetime is 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`). Expired or garbage tokens → 401.

## Doctor catalog (no login)

Active doctors only. Emails and passwords are not included.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/doctors` | Optional `?specialization=` (substring, case-insensitive) |
| GET | `/api/doctors/{doctor_id}` | 404 if missing |
| GET | `/api/doctors/{doctor_id}/availability?date=YYYY-MM-DD` | Server-generated slots for that calendar date |

Availability response: `doctor_id`, `date`, `slot_duration_minutes`, `is_active`, `slots: [{ start_datetime, end_datetime }]`. Empty `slots` for weekends without hours, leave days, inactive doctors, and fully booked days. Past times on the current day are omitted.

## Appointments

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/appointments/hold` | patient | Create a slot hold. 201. Conflict → 409. |
| POST | `/api/appointments/confirm` | patient | Convert hold + required `symptoms`. 201 `confirmed`. |
| GET | `/api/appointments` | any | Patient: own rows. Doctor: assigned rows. Admin: all. |
| GET | `/api/appointments/{id}` | any with access | Cross-user → 403. Missing → 404. |
| GET | `/api/appointments/{id}/previsit-summary` | patient / assigned doctor / admin | Original symptoms plus AI fields. `raw_response` only for doctor/admin. |
| POST | `/api/appointments/{id}/previsit-summary/retry` | patient / assigned doctor / admin | Regenerates from stored symptoms. |
| GET | `/api/appointments/{id}/visit` | access | Visit payload. Clinical notes and `summary_raw_response` are omitted for patients. |
| POST | `/api/appointments/{id}/visit` | **assigned doctor only** | Clinical notes; optional follow-up and medications. Marks appointment `completed`. 403 otherwise. |
| POST | `/api/appointments/{id}/visit/summary/retry` | assigned doctor | Regenerates the patient-friendly summary. |
| POST | `/api/appointments/{id}/reschedule` | patient | `{ "hold_id": n }` for the same doctor. 201 new appointment. |
| POST | `/api/appointments/{id}/cancel` | patient, assigned doctor, or admin | Pending/confirmed only. History kept (`cancelled`). |

Hold body:

```json
{
  "doctor_id": 1,
  "start_datetime": "2026-09-07T09:00:00+00:00",
  "end_datetime": "2026-09-07T09:30:00+00:00"
}
```

Confirm body:

```json
{
  "hold_id": 12,
  "symptoms": "Headache for three days, worse in the morning.",
  "reason": "Optional visit reason"
}
```

Cancel body: `{ "reason": "optional text" }` (or `{}`).

Visit body:

```json
{
  "clinical_notes": "Examination findings…",
  "follow_up_instructions": "Return in two weeks if symptoms persist.",
  "medications": [
    {
      "medicine_name": "Ibuprofen",
      "dosage": "400mg",
      "frequency": "twice daily at 08:00 and 20:00",
      "duration": "5 days",
      "instructions": "After food"
    }
  ]
}
```

Medication reminders are created only when frequency includes explicit clock times. See `docs/background-jobs.md`.

Appointment statuses: `pending`, `confirmed`, `completed`, `cancelled`, `cancelled_leave`, `rescheduled`.

## Current patient

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/api/me/medication-reminders` | patient | Reminder rows derived from prescriptions |

## Admin

All `/api/admin/*` routes require `users.role = admin` (403 otherwise, 401 without a valid token).

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/admin/dashboard` | `{ status, service, role }` — authorization probe. The admin UI loads counts from other endpoints. |
| GET | `/api/admin/notifications` | Optional `?status=`. Does not include secrets. |
| POST | `/api/admin/doctors` | Create doctor user + profile. Email must be unique. |
| GET | `/api/admin/doctors` | All doctors including inactive, with hours and leave |
| GET | `/api/admin/doctors/{id}` | |
| PATCH | `/api/admin/doctors/{id}` | Name, specialization, qualification, bio, slot duration, `is_active` |
| POST | `/api/admin/doctors/{id}/activate` | |
| POST | `/api/admin/doctors/{id}/deactivate` | Inactive doctors have no bookable slots |
| PUT | `/api/admin/doctors/{id}/working-hours` | Replace hours for the doctor. `{ "hours": [ { "day_of_week", "start_time", "end_time" } ] }`. `day_of_week`: 0 = Monday … 6 = Sunday. Slot duration 5–180 minutes. |
| POST | `/api/admin/doctors/{id}/leave` | Record leave; cancel overlapping pending/confirmed visits. Alias: `/leaves`. |

Create doctor body:

```json
{
  "email": "doctor@example.com",
  "password": "at-least-8-characters",
  "full_name": "Dr Example",
  "specialization": "Cardiology",
  "qualification": "MD",
  "bio": "optional",
  "slot_duration_minutes": 30,
  "is_active": true,
  "working_hours": [
    { "day_of_week": 0, "start_time": "09:00:00", "end_time": "17:00:00" }
  ]
}
```

Leave body: `{ "start_date": "2026-09-07", "end_date": "2026-09-07", "reason": "Conference" }`. Response includes `cancelled_appointment_ids`.

There is no public register-as-admin endpoint. See README (first admin).

## Google Calendar

Mounted at `/api/v1/calendar`. Tokens are never in responses.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/api/v1/calendar/connect` | any user | `{ authorization_url, provider }`. 503 if client id/secret unset. |
| GET | `/api/v1/calendar/callback` | none (Google redirect) | Exchanges `code` + `state`, stores tokens, redirects to success/failure URL. |
| GET | `/api/v1/calendar/status` | any user | `{ connected, provider, google_calendar_id }` |
| POST | `/api/v1/calendar/disconnect` | any user | Clears stored tokens |

Setup: `docs/google-calendar-setup.md`.

## Error shape

FastAPI `HTTPException` bodies use `{ "detail": "…" }` (string or validation list). Common codes:

| Code | Typical cause |
| --- | --- |
| 401 | Missing, invalid, or expired JWT; bad login |
| 403 | Wrong role or another user’s resource |
| 404 | Unknown doctor, appointment, or hold |
| 409 | Slot taken, overlapping leave, duplicate email, expired hold |
| 422 | Validation (empty symptoms, bad times, slot duration bounds) |
| 503 | Google OAuth not configured |

## Related docs

- Slot holds: `docs/slot-hold-mechanism.md`
- Double-booking: `docs/double-booking-prevention.md`
- Leave: `docs/leave-conflict-handling.md`
- LLM: `docs/llm-prompts.md`
- Testing: `docs/testing.md`
