# Slot-hold mechanism

A hold is a short-lived, server-side lock on a doctor’s time range. Patients hold a slot, enter symptoms, then confirm. The backend `expires_at` timestamp is the source of truth. The countdown on the booking page is display-only.

Default lifetime is **5 minutes** (`SLOT_HOLD_MINUTES`).

## Why holds exist

Availability is generated on read. Two patients can open the same slot at the same time. A hold:

- occupies the range so the second patient gets HTTP 409 on hold or confirm
- gives the first patient time to type symptoms without creating an appointment yet
- expires so abandoned checkouts do not block the clinic calendar

A hold is not an appointment. History, email, and calendar sync start only after confirm.

## Create a hold

`POST /api/appointments/hold` (patient JWT)

```json
{
  "doctor_id": 1,
  "start_datetime": "2026-09-07T09:00:00+00:00",
  "end_datetime": "2026-09-07T09:30:00+00:00"
}
```

The handler (`hold_slot` in `backend/app/services/appointments.py`) runs in one transaction:

1. Resolve the patient profile (doctors and admins receive 403).
2. `SELECT doctor_profiles … FOR UPDATE`.
3. Reject inactive doctors.
4. Mark that doctor’s holds with `expires_at <= now()` as `expired`.
5. Re-generate bookable slots on the server (do not trust the client range beyond matching a generated slot).
6. `INSERT` `appointment_slot_holds` with `status = active` and `expires_at = now + SLOT_HOLD_MINUTES`.
7. Commit. A GiST exclusion failure becomes HTTP 409.

Response includes `id`, the slot, `expires_at`, and `status`.

## Exclusion constraint

Active holds for the same doctor cannot overlap:

```sql
EXCLUDE USING gist (
    doctor_id WITH =,
    tstzrange(start_datetime, end_datetime, '[)') WITH &&
)
WHERE (status = 'active')
```

Constraint name: `ex_slot_holds_doctor_overlap`.

PostgreSQL cannot use `now()` inside that predicate. Time passing does not change existing rows. Expired holds must be updated to `expired`, `converted`, or `released` so they drop out of the constraint.

## Hold statuses

| Status | Meaning |
| --- | --- |
| `active` | Blocks overlapping holds and bookings |
| `expired` | `expires_at` reached, or confirm rejected an overdue hold |
| `converted` | Confirm or reschedule succeeded |
| `released` | Doctor leave (or similar processing) freed the range |

## Expiration

On every hold, confirm, and reschedule for that doctor, the service expires stale rows **before** generating slots:

`status = 'active' AND expires_at <= now()` → `expired`

Confirm also compares the caller’s hold to `now` even if the status was not yet flipped. An overdue hold cannot be confirmed.

Expired holds no longer appear in availability and no longer participate in `ex_slot_holds_doctor_overlap`.

## Confirm

`POST /api/appointments/confirm`

```json
{
  "hold_id": 12,
  "symptoms": "Headache for three days",
  "reason": "Follow-up"
}
```

`symptoms` is required (non-empty after trim). Confirm:

1. Loads the hold; 404 if missing; 403 if it belongs to another patient.
2. Locks the doctor, expires stale holds, refreshes the hold.
3. Rejects expired or non-active holds (409).
4. Re-checks server-generated availability, ignoring this hold id.
5. Inserts a `confirmed` appointment, symptom row, and pending AI summary in the **same** transaction.
6. Marks the hold `converted`.
7. Commits. Gemini, email, and calendar run after commit.

A patient cannot confirm another patient’s hold.

## Frontend

`frontend/src/pages/patient/Book.jsx` posts the hold, shows remaining seconds from `expires_at`, then posts confirm. If the timer hits zero, the API still decides: confirm returns 409 when `expires_at` has passed.

HTTP 409 from a competing booking is shown as:

`This slot was just booked by another patient. Please select another slot.`

(`frontend/src/lib/format.js`)

## Reschedule

`POST /api/appointments/{id}/reschedule` with `{ "hold_id": … }` uses a new hold on the **same doctor**. The old appointment becomes `rescheduled` and the new row is `confirmed` in one transaction. See `docs/double-booking-prevention.md`.

## Tests

- `tests/test_appointments.py` — hold, second-hold conflict, expired confirm, concurrent confirm
- `tests/test_availability.py` — active hold hides a slot; expired hold does not
