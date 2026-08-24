# Database schema

CareConnect uses PostgreSQL. Tables are created by SQLAlchemy models and applied with Alembic (`alembic upgrade head` from `backend/`). Migration `0001_initial_schema` enables `btree_gist` and creates the tables.

Timestamps `created_at` and `updated_at` are timezone-aware on every table.

Primary keys are integers. Foreign keys use `ON DELETE RESTRICT` where history must be preserved (appointments, clinical records) and `ON DELETE CASCADE` for owned child rows (working hours, medications, holds).

## Tables

### users

Authentication identity for every role.

| Column | Type | Notes |
| --- | --- | --- |
| id | integer PK | |
| email | varchar(255) | unique, indexed |
| hashed_password | varchar(255) | never store plaintext |
| full_name | varchar(255) | |
| role | varchar(32) | `patient`, `doctor`, or `admin` |
| is_active | boolean | login disabled when false |
| created_at, updated_at | timestamptz | |

Public registration may only create `patient` users. Admin and doctor accounts are created by administrators.

### patient_profiles

One-to-one with `users` (`user_id` unique).

| Column | Type | Notes |
| --- | --- | --- |
| id | integer PK | |
| user_id | FK users | unique, cascade delete |
| date_of_birth | date | nullable |
| phone | varchar(32) | indexed |
| address | text | |
| gender | varchar(32) | |
| emergency_contact_name | varchar(255) | |
| emergency_contact_phone | varchar(32) | |

### doctor_profiles

One-to-one with `users` (`user_id` unique).

| Column | Type | Notes |
| --- | --- | --- |
| id | integer PK | |
| user_id | FK users | unique, cascade delete |
| specialization | varchar(128) | indexed; searched by patients |
| qualification | varchar(255) | |
| bio | text | |
| slot_duration_minutes | integer | must be > 0; default 30 |
| is_active | boolean | inactive doctors cannot be booked |

### doctor_working_hours

| Column | Type | Notes |
| --- | --- | --- |
| id | integer PK | |
| doctor_id | FK doctor_profiles | cascade delete |
| day_of_week | integer | 0 = Monday … 6 = Sunday |
| start_time | time | |
| end_time | time | must be after `start_time` |

Unique on `(doctor_id, day_of_week, start_time)` so a doctor may have more than one shift on the same day.

### doctor_leaves

| Column | Type | Notes |
| --- | --- | --- |
| id | integer PK | |
| doctor_id | FK doctor_profiles | cascade delete |
| start_date | date | inclusive |
| end_date | date | inclusive; must be >= `start_date` |
| reason | text | |
| status | varchar(32) | `scheduled`, `processed`, `cancelled` |
| created_by_admin_id | FK users | nullable |

Non-cancelled leave ranges for the same doctor cannot overlap (`ex_doctor_leaves_no_overlap`). Leave processing must not delete appointments; it marks them `cancelled_leave` and writes notification rows.

### appointments

| Column | Type | Notes |
| --- | --- | --- |
| id | integer PK | |
| patient_id | FK patient_profiles | `ON DELETE RESTRICT` |
| doctor_id | FK doctor_profiles | `ON DELETE RESTRICT` |
| start_datetime | timestamptz | |
| end_datetime | timestamptz | must be after start |
| status | varchar(32) | see statuses below |
| reason | text | |
| cancellation_reason | text | |
| cancelled_at | timestamptz | |
| rescheduled_from_appointment_id | FK appointments | preserves history |
| created_at, updated_at | timestamptz | required |

Statuses: `pending`, `confirmed`, `completed`, `cancelled`, `cancelled_leave`, `rescheduled`.

Blocking statuses for the same doctor (`pending`, `confirmed`, `completed`) cannot overlap. See `docs/double-booking-prevention.md`.

Indexes: `(doctor_id, start_datetime)`, `(patient_id, start_datetime)`, `status`.

### appointment_slot_holds

Temporary lock before confirmation. The backend `expires_at` value is the source of truth, not any frontend timer.

| Column | Type | Notes |
| --- | --- | --- |
| id | integer PK | |
| patient_id | FK patient_profiles | |
| doctor_id | FK doctor_profiles | |
| start_datetime | timestamptz | |
| end_datetime | timestamptz | |
| expires_at | timestamptz | |
| status | varchar(32) | `active`, `expired`, `converted`, `released` |

Active holds for the same doctor cannot overlap (`ex_slot_holds_doctor_overlap`). Expired holds must be marked `expired` so they no longer participate in that constraint.

### symptom_submissions

One submission per appointment (`appointment_id` unique). Symptoms are stored even if Gemini fails.

### ai_symptom_summaries

One summary row per symptom submission. Fields: `urgency_level` (`Low` / `Medium` / `High`), `chief_complaint`, `suggested_questions` (JSONB), `raw_response`, `status` (`pending` / `succeeded` / `failed`), `error_message`, `generated_at`.

LLM failure updates `status` and `error_message`; it does not roll back the symptom row.

### visit_notes

One note per appointment. Stores clinical notes, optional `follow_up_instructions`, plus the patient-friendly summary and its AI status (`summary_status`, `summary_error`, `summary_raw_response`, `summary_generated_at`). LLM failure does not roll back the note or prescription.

### prescriptions

One prescription per appointment. Links doctor and patient.

### prescription_medications

Child rows of a prescription: `medicine_name`, `dosage`, `frequency`, `duration`, `instructions`. Frequency is stored exactly as entered; reminder jobs must not invent instructions.

### medication_reminders

Built from explicit prescription frequency.

| Column | Type | Notes |
| --- | --- | --- |
| prescription_medication_id | FK | |
| patient_id | FK patient_profiles | |
| remind_at | time | time of day |
| start_date, end_date | date | from duration |
| next_scheduled_at | timestamptz | for the reminder worker |
| last_sent_at | timestamptz | |
| status | varchar(32) | `active`, `completed`, `cancelled` |

### notification_logs

Email (and future channel) attempts. Status: `pending`, `sent`, `failed`, `retrying`. `idempotency_key` is unique so Celery retries do not insert duplicate notification rows. Email failure must not roll back an appointment.

### calendar_integrations

OAuth tokens for Google Calendar. One row per user and provider. Tokens are never sent to the frontend.

### calendar_events

Idempotent sync records. Unique `(appointment_id, user_id)` prevents duplicate events on retry. Unique `(calendar_integration_id, provider_event_id)` where `provider_event_id` is present prevents duplicate Google event ids. `sync_status`: `pending`, `synced`, `failed`, `deleted`. Calendar failure must not cancel a valid appointment.

## Entity relationships

```
users 1──1 patient_profiles
users 1──1 doctor_profiles
users 1──1 calendar_integrations
doctor_profiles 1──* doctor_working_hours
doctor_profiles 1──* doctor_leaves
patient_profiles 1──* appointments
doctor_profiles 1──* appointments
patient_profiles 1──* appointment_slot_holds
doctor_profiles 1──* appointment_slot_holds
appointments 1──1 symptom_submissions
symptom_submissions 1──1 ai_symptom_summaries
appointments 1──1 visit_notes
appointments 1──1 prescriptions
prescriptions 1──* prescription_medications
prescription_medications 1──* medication_reminders
appointments 1──* notification_logs
appointments 1──* calendar_events
calendar_integrations 1──* calendar_events
```

## Extensions

PostgreSQL extension `btree_gist` is required for exclusion constraints that combine equality on integer ids with range overlap.
