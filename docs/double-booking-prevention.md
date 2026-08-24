# Double-booking prevention

CareConnect must never persist two successful appointments for the same doctor when their time ranges overlap. Frontend availability checks are not sufficient. Protection is enforced in PostgreSQL.

## Why a unique start time is not enough

Slot duration is configurable per doctor. Two bookings can overlap even when they do not share the same `start_datetime` (for example 10:00–11:00 and 10:30–11:00). A unique constraint on `(doctor_id, start_datetime)` would miss that case.

The database therefore treats each appointment as a half-open time range:

`tstzrange(start_datetime, end_datetime, '[)')`

Adjacent appointments such as 10:00–10:30 and 10:30–11:00 do not overlap.

## Exclusion constraint

Table `appointments` has:

```sql
EXCLUDE USING gist (
    doctor_id WITH =,
    tstzrange(start_datetime, end_datetime, '[)') WITH &&
)
WHERE (status IN ('pending', 'confirmed', 'completed'))
```

Constraint name: `ex_appointments_doctor_overlap`.

This requires the `btree_gist` extension so an integer `doctor_id` can participate in a GiST exclusion constraint.

Cancelled history rows (`cancelled`, `cancelled_leave`, `rescheduled`) are excluded from the constraint so they do not block a later booking of the same slot. Appointment history is preserved.

If two transactions insert overlapping blocking rows for the same doctor:

- one insert commits
- the other fails with a PostgreSQL exclusion-constraint error
- the API maps that error to **HTTP 409 Conflict**

GiST exclusion constraints lock the conflicting index range. Concurrent inserts do not both succeed.

## Slot holds

`POST /api/appointments/hold` creates a temporary hold. Default duration is **5 minutes** (`SLOT_HOLD_MINUTES`). The backend `expires_at` timestamp is the source of truth. A frontend countdown is display-only.

Active holds use the same overlap rule (`ex_slot_holds_doctor_overlap`) while `status = 'active'`.

PostgreSQL cannot use `now()` in that constraint to expire holds automatically. Time passing does not re-evaluate existing rows. In the booking transaction the backend:

1. Marks holds with `expires_at <= now()` as `expired`.
2. Expired holds then drop out of the exclusion constraint and do not block new bookings.
3. Rejects confirmation if the caller's hold is expired, even if `status` is still `active`.

## Transaction recipe for confirmation

`POST /api/appointments/confirm` is the final booking operation. Availability re-check and appointment insert run in **one PostgreSQL transaction**:

1. `BEGIN`
2. `SELECT … FROM doctor_profiles WHERE id = :doctor_id FOR UPDATE`  
   Serializes booking attempts for that doctor. Inactive doctors are rejected.
3. Expire stale holds for that doctor (`status = 'active'` and `expires_at <= now()`).
4. Re-generate bookable slots on the server (working hours, duration, leave, appointments, remaining holds, current time). Do not trust the client.
5. Reject another patient's active hold on the same range.
6. `INSERT` the appointment with status `confirmed`.
7. Insert the patient's original symptoms and a pending AI summary row.
8. Mark the caller's hold `converted`.
9. `COMMIT`
10. Call Gemini **after** commit. Failure updates the AI summary row only.

If step 6 races with another commit, `ex_appointments_doctor_overlap` still aborts the loser. Application checks reduce conflicts; the exclusion constraint is the guarantee.

Gemini, email, and calendar writes happen after commit. Integration failure must not roll back a valid appointment. See `docs/llm-prompts.md`.

## Concurrency test

`tests/test_appointments.py::test_concurrent_booking_same_slot_returns_one_conflict` starts two HTTP pipelines at the same time. Each patient tries to hold and confirm the same doctor and time.

Expected result:

- one pipeline returns **201**
- the other returns **409 Conflict**
- exactly one confirmed appointment row exists for that doctor and slot

This is enforced by `FOR UPDATE` on the doctor row, hold/appointment exclusion constraints, and mapping `IntegrityError` to HTTP 409.

## Reschedule

`POST /api/appointments/{id}/reschedule` takes a hold on the new slot. Old and new rows are written in **one transaction**:

1. `SELECT … FROM doctor_profiles WHERE id = :doctor_id FOR UPDATE`
2. `SELECT … FROM appointments WHERE id = :appointment_id FOR UPDATE`
3. Re-check that the appointment is still `pending` or `confirmed` (a concurrent reschedule or cancel then returns 409)
4. Expire stale holds and re-generate bookable slots on the server
5. Mark the existing row `rescheduled` (it drops out of `ex_appointments_doctor_overlap` and frees the old slot)
6. Insert the replacement `confirmed` row with `rescheduled_from_appointment_id`
7. Mark the new hold `converted`
8. `COMMIT`

A failed insert rolls back the status change, so the original appointment remains. This is not cancel-then-create across two commits.

Email (patient and doctor) and calendar update run after commit. Integration failure does not undo the reschedule.

`tests/test_cancel_reschedule.py::test_simultaneous_rescheduling` starts two HTTP reschedules of the same appointment at the same time. One returns **201**; the other returns **409**. Exactly one new confirmed row exists.

## What this does not replace

Leave handling, inactive doctors, and past-slot rejection are additional application rules. They do not replace the exclusion constraint. The constraint exists so two simultaneous HTTP requests for the same doctor and overlapping time cannot both create appointments.
