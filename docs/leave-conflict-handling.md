# Leave conflict handling

When an administrator records doctor leave, CareConnect must stop new bookings for that period and must not silently delete existing appointments.

## Create leave

`POST /api/admin/doctors/{doctor_id}/leave`

Body:

```json
{
  "start_date": "2026-09-07",
  "end_date": "2026-09-07",
  "reason": "Conference"
}
```

Dates are inclusive. The same handler is also available at `POST /api/admin/doctors/{doctor_id}/leaves`.

## Transaction

Leave processing runs in one PostgreSQL transaction:

1. `SELECT doctor_profiles … FOR UPDATE` so concurrent bookings for that doctor wait.
2. Insert the `doctor_leaves` row. Overlapping non-cancelled leave fails with HTTP 409 and rolls back.
3. Select pending and confirmed appointments whose time range overlaps the leave window, `FOR UPDATE`.
4. Mark each affected appointment `cancelled_leave`. Set `cancelled_at` and `cancellation_reason`. Do not delete the row.
5. Insert `notification_logs` rows for each affected patient (`doctor_leave_cancellation`, status `pending`) and for the doctor (`doctor_leave_processed`).
6. Release active slot holds that overlap the leave window.
7. Set leave status to `processed`.
8. `COMMIT`

If any step fails, the leave row, appointment status changes, and notification rows are all rolled back.

## Prevent new bookings

Availability generation already returns no slots on non-cancelled leave days. Hold and confirm re-check that list inside their own transactions, so a booking during leave returns HTTP 409.

## Affected appointments

An appointment is affected when:

- it belongs to the doctor
- status is `pending` or `confirmed`
- its `[start_datetime, end_datetime)` range overlaps the leave calendar window (start date 00:00 UTC through end date 24:00 UTC)

Completed, already cancelled, and rescheduled rows are left unchanged.

## History

Cancelled-for-leave visits keep their primary key, patient, doctor, original times, and reason for the visit. Patients can still `GET /api/appointments` and `GET /api/appointments/{id}`. The status is `cancelled_leave`, not a missing record.

## Patient-visible reason

`cancellation_reason` is stored on the appointment and returned in the appointment API. The text always states that the doctor is on leave. If the admin supplied a leave reason, it is appended.

Example:

`Your appointment was cancelled because the doctor is on leave. Reason: Conference`

## Notifications

Leave processing writes `notification_logs` rows in the same transaction. Email delivery is a background job (`docs/background-jobs.md`, `docs/notification-failure-handling.md`) and must not roll back leave processing. Patient keys are unique per leave and appointment so retries do not insert duplicates (`leave:{leave_id}:appointment:{appointment_id}:patient:{user_id}`). Overlapping Google Calendar events for affected visits are deleted after commit.
