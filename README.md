# CareConnect

Healthcare Appointment & Follow-up Manager

## Objective

Give a clinic one system where patients book visits, doctors record notes and prescriptions, and administrators manage doctor capacity — with PostgreSQL enforcing that a doctor is never double-booked, even when two patients confirm the same slot at the same time.

## Problem statement

Clinic booking often fails in the gap between “the slot looked free” and “the row was saved.” Slot length varies by doctor, holds expire, leave cancels existing visits, and email or calendar outages must not undo a confirmed appointment. CareConnect treats PostgreSQL exclusion constraints as the source of truth, generates availability on the server, and keeps Gemini, SendGrid, and Google Calendar off the commit path for clinical data.

## Features

- Patient self-registration and JWT login; doctor and admin accounts created by administrators
- Role-separated portals (patient, doctor, admin)
- Server-generated availability from working hours, slot duration, leave, holds, and existing visits
- Five-minute slot holds, then confirm with required symptoms
- Concurrent booking: exactly one of two simultaneous confirms succeeds (HTTP 409 for the other)
- Cancel (history preserved) and reschedule (one transaction, not cancel-then-create)
- Doctor leave: overlapping pending/confirmed visits become `cancelled_leave`; patients are emailed; rows are not deleted
- Gemini pre-visit summary and post-visit patient-friendly summary, with retry; booking and notes still save if Gemini fails
- SendGrid email for booking, reminders, cancellation, leave, reschedule, and medication times that the doctor wrote explicitly
- Optional Google Calendar sync (OAuth; tokens never sent to the browser)
- Admin doctor CRUD, working hours, activate/deactivate, leave, appointment list, notification log

Not in this repository: password reset, MFA, SMS, payments, video visits, profile editing APIs, Docker/Compose, or a frontend unit-test suite.

## Patient portal

Routes under `/patient` (JWT role `patient`).

| Screen | What it does |
| --- | --- |
| Dashboard | Entry to the patient’s visits |
| Find a doctor | Catalog of **active** doctors; optional specialization filter (`GET /api/doctors`) |
| Doctor profile | Bio, hours, pick a date, load server slots, start booking |
| Book | `POST /api/appointments/hold`, countdown from `expires_at`, then confirm with symptoms |
| Appointments | List and detail: status, times, pre-visit summary, visit summary and prescription when present |
| Reschedule | New hold for the same doctor, then `POST /api/appointments/{id}/reschedule` |
| Reminders | `GET /api/me/medication-reminders` |
| Calendar | Connect or disconnect Google Calendar |
| Profile | Read-only name, email, role, and active flag from `/api/auth/me` |

Public registration (`/register`) always creates a patient. A `role` field in the register body is ignored.

## Doctor portal

Routes under `/doctor` (JWT role `doctor`).

| Screen | What it does |
| --- | --- |
| Dashboard | Assigned appointments |
| Appointments | Only this doctor’s visits (API-enforced) |
| Appointment detail | Symptoms, pre-visit AI summary (retry), clinical notes, optional follow-up and medications, patient-friendly summary (retry) |
| Calendar | Google Calendar connect/disconnect |
| Profile | Read-only account fields |

Doctors cannot hold slots or create doctor accounts. Only the **assigned** doctor may `POST /api/appointments/{id}/visit`. Another doctor receives 403.

## Admin portal

Routes under `/admin` (JWT role `admin`). There is no public admin registration.

| Screen | What it does |
| --- | --- |
| Dashboard | Counts from doctors, appointments, and notification logs (the `/api/admin/dashboard` JSON is a role check, not those counts) |
| Doctors | Create, edit, activate, deactivate |
| Working hours | Replace hours per weekday (0 = Monday … 6 = Sunday); slot duration 5–180 minutes |
| Leave | Inclusive date range; cancels overlapping pending/confirmed visits |
| Appointments | All clinic appointments |
| Notifications | Email outbox statuses (`pending`, `retrying`, `sent`, `failed`) |

## Technology stack

| Layer | Stack |
| --- | --- |
| Frontend | React 19, Vite 6, Tailwind CSS 4, React Router 7, Axios |
| Backend | Python, FastAPI, Pydantic Settings, SQLAlchemy 2, Alembic, Uvicorn |
| Auth | bcrypt (passlib), JWT HS256 (`python-jose`) |
| Database | PostgreSQL (`btree_gist` exclusion constraints) |
| Jobs | Celery 5, Redis |
| AI | Google Gemini (`google-generativeai`, default model `gemini-1.5-flash`) |
| Email | SendGrid |
| Calendar | Google Calendar API + OAuth 2.0 (`google-auth-oauthlib`) |

Developed with Python 3.13 and Node.js 18+. Use a current Python 3.11+ and Node 18+ install.

## Architecture

React talks only to FastAPI. FastAPI commits booking and clinical rows to PostgreSQL, then calls Gemini in-process (30s timeout) and enqueues email/calendar work to Redis. Celery workers call SendGrid and Google. Integration failure never rolls back a committed appointment.

Details: [`docs/architecture.md`](docs/architecture.md).

## Project structure

```
CareConnect/
├── README.md
├── .env.example                 # combined reference; secrets left empty
├── .gitignore
├── docs/                        # design and operations (see list below)
├── backend/
│   ├── alembic/                 # migrations (0001 schema, 0002 hours, 0003 follow-up)
│   ├── app/
│   │   ├── api/                 # HTTP routers
│   │   ├── core/                # settings, JWT, clock
│   │   ├── db/                  # engine and sessions
│   │   ├── integrations/        # Gemini, SendGrid, Google adapters
│   │   ├── models/              # SQLAlchemy
│   │   ├── schemas/             # Pydantic
│   │   ├── services/            # transactions and rules
│   │   ├── tasks/               # Celery
│   │   ├── celery_app.py
│   │   └── main.py              # FastAPI app
│   ├── tests/
│   ├── requirements.txt
│   ├── alembic.ini
│   └── pytest.ini
└── frontend/
    ├── src/
    │   ├── api/client.js
    │   ├── components/
    │   ├── context/
    │   ├── pages/               # patient, doctor, admin, auth
    │   └── App.jsx
    ├── package.json
    └── vite.config.js           # dev server port 5173
```

## Prerequisites

- Python 3.11+ (3.13 used in development)
- Node.js 18+
- PostgreSQL
- Redis (needed for live email, calendar sync, and reminders; **not** required for pytest)
- Optional: Gemini API key, SendGrid API key and verified sender, Google Cloud OAuth client

## Installation

Clone or copy the project, then configure environment files **before** starting the API. The example files leave secrets empty on purpose; an empty `DATABASE_URL=` in a copied `.env` overrides the code default and will fail.

```bash
cd CareConnect
copy .env.example backend\.env
copy frontend\.env.example frontend\.env
```

On macOS/Linux use `cp` instead of `copy`.

Edit `backend/.env` and set at least:

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/careconnect
JWT_SECRET_KEY=a-long-random-secret-not-the-placeholder
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
CORS_ORIGINS=http://localhost:5173
```

Use your actual PostgreSQL username, password, host, and database name. Do not commit `backend/.env` or `frontend/.env`.

`frontend/.env` should contain:

```
VITE_API_URL=http://localhost:8000
```

Restart `npm run dev` after changing `VITE_*` variables.

## Environment variables

Full list: [`.env.example`](.env.example) and [`backend/.env.example`](backend/.env.example). Loaded by `backend/app/core/config.py` from `.env` in the process working directory (run uvicorn from `backend/` so `backend/.env` applies).

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL URL |
| `JWT_SECRET_KEY` | HS256 secret. Production (`APP_ENV=production`) rejects `replace-with-a-long-random-secret` |
| `JWT_ALGORITHM` | Default in code: `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Default in code: `30` |
| `CORS_ORIGINS` | Comma-separated browser origins |
| `SLOT_HOLD_MINUTES` | Hold lifetime (default 5) |
| `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Redis for Celery |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Pre-visit and post-visit summaries |
| `SENDGRID_API_KEY` / `SENDGRID_FROM_EMAIL` | Outbound email |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Calendar OAuth |
| `GOOGLE_REDIRECT_URI` | Must match the Cloud Console URI exactly |
| `NOTIFICATION_MAX_RETRIES` | Email attempt cap (default 5) |
| `APPOINTMENT_REMINDER_HOURS` | Reminder window (default 24) |
| `VITE_API_URL` | Frontend API base (Vite; `frontend/.env` only) |

Never put live keys in `.env.example`, source, or git.

## Database setup

1. Create a database (example name `careconnect`).
2. From `backend/`, apply migrations (this also enables `btree_gist`):

```bash
cd backend
.\.venv\Scripts\activate
alembic upgrade head
```

Schema: [`docs/database-schema.md`](docs/database-schema.md).

### First admin

Public register cannot create admins. After migrations, from `backend/` with the venv active:

```bash
python -c "from app.db.session import SessionLocal; from app.models.enums import UserRole; from app.services.auth import create_user_with_role; db=SessionLocal(); create_user_with_role(db, email='admin@example.com', password='choose-a-strong-password', full_name='Clinic Admin', role=UserRole.ADMIN); print('admin created')"
```

Then sign in at `/login`. Create doctors in the admin portal. Change the password example to a password you actually chose; do not reuse this string in production.

## Backend setup

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Unix activate: `source .venv/bin/activate`.

API: `http://localhost:8000`  
Health: `GET http://localhost:8000/health`  
OpenAPI: `http://localhost:8000/docs`

Run uvicorn from `backend/` so `app.main:app` and `backend/.env` resolve.

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

App: `http://localhost:5173` (Vite config port 5173). Production build: `npm run build` (output `frontend/dist`).

The UI sends `Authorization: Bearer` from `localStorage` key `careconnect_token`. A 401 (except login/register) clears the token.

## Redis / Celery setup

Required for live email, calendar sync, appointment reminders, and medication reminders. Pytest sets Celery eager mode and does not need Redis.

Start Redis, then two processes from `backend/` with the venv active:

```bash
celery -A app.celery_app worker -l info --pool=solo
celery -A app.celery_app beat -l info
```

Windows workers need `--pool=solo`. Schedules: [`docs/background-jobs.md`](docs/background-jobs.md). Failure and retry: [`docs/notification-failure-handling.md`](docs/notification-failure-handling.md).

If Redis is down during an HTTP request, the appointment still commits; outbox rows stay `pending` until workers run.

## Gemini setup

1. Create an API key in Google AI Studio / Google Cloud for Gemini.
2. Set `GEMINI_API_KEY` in `backend/.env`. Optional: `GEMINI_MODEL=gemini-1.5-flash`.
3. Restart uvicorn.

Prompts and failure rules: [`docs/llm-prompts.md`](docs/llm-prompts.md).

If the key is missing or the call times out (30s) or returns invalid JSON, confirm still returns 201 and visit notes still save. Status is stored as `failed`; patients and doctors can retry from the appointment screens.

Gemini is assistive only and is labeled as not a medical diagnosis.

## SendGrid setup

1. Create a SendGrid API key with mail-send permission.
2. Verify a sender identity.
3. Set `SENDGRID_API_KEY` and `SENDGRID_FROM_EMAIL` in `backend/.env`.
4. Run Celery worker and beat.

Without these variables, send attempts fail, rows go `retrying` then `failed`, and appointments remain valid. Admins can inspect `/admin/notifications`.

## Google Calendar setup

Step-by-step Cloud Console instructions: [`docs/google-calendar-setup.md`](docs/google-calendar-setup.md).

Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/calendar/callback` (must match the console). Patients and doctors connect from the Calendar page. If credentials are unset, `GET /api/v1/calendar/connect` returns 503. Tokens are stored server-side only.

## API documentation

Endpoint tables, bodies, and error codes: [`docs/api-documentation.md`](docs/api-documentation.md).

While the API is running: Swagger UI at `/docs`, ReDoc at `/redoc`. Login uses a JSON body; paste the returned `access_token` as a Bearer token in Swagger.

## Testing

```bash
cd backend
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/careconnect"
.\.venv\Scripts\python.exe -m pytest -v
```

```bash
cd frontend
npm run build
```

Coverage map (auth, holds, concurrency, leave, Gemini, email, calendar, secrets scan): [`docs/testing.md`](docs/testing.md).

Google, SendGrid, and Gemini are faked in tests. Do not weaken assertions to get a green run.

## Deployment

This repository does not include Docker or cloud templates. A production layout that matches the code:

1. PostgreSQL with migrations (`alembic upgrade head`).
2. Redis and Celery worker + beat (same app as local).
3. API process: `uvicorn app.main:app` (or an equivalent ASGI server) behind HTTPS.
4. Static frontend: `npm run build` and serve `frontend/dist`.
5. Environment:
   - `APP_ENV=production`
   - `JWT_SECRET_KEY` set to a long random value (placeholder is rejected)
   - `CORS_ORIGINS` set to the real frontend origin
   - `VITE_API_URL` baked in at **frontend build** time
   - `GOOGLE_REDIRECT_URI` and OAuth console URI updated to the public API callback
   - `GOOGLE_OAUTH_*_REDIRECT` pointed at the public frontend
6. Do not expose `/docs` on a public host unless you intend to.
7. Keep `.env` off the image and out of git.

## Security

- Passwords hashed with bcrypt; never returned in JSON
- JWT `sub` is the user id; authorization uses `users.role` in the database
- Register cannot create doctor or admin
- Cross-user appointment GET/cancel is 403
- Only the assigned doctor submits visit notes
- `.env` is gitignored; example files keep secret values empty
- Calendar tokens never appear in API responses
- `APP_ENV=production` refuses the development JWT placeholder
- Source scan in `tests/test_security.py` fails if private keys or live SendGrid/Gemini/Google token patterns are committed

Frontend route guards are navigation only.

## Known limitations

- No password reset, email verification, or MFA
- No first-admin CLI; use `create_user_with_role` as in Database setup
- Profile UI is read-only; `patient_profiles` columns exist but there is no profile-update API
- Email channel only (no SMS or push)
- Gemini runs on the HTTP request after commit (up to 30 seconds), not as a Celery task
- Confirm/visit HTTP success does not mean email, calendar, or Gemini succeeded
- Medication reminders require **explicit clock times** in frequency text
- Doctor catalog `GET /api/doctors` is unauthenticated (no emails)
- No Docker, CI config, or cloud IaC in this repo
- No frontend unit tests; QA is pytest plus `npm run build`
- `python-jose` emits `datetime.utcnow()` deprecation warnings
- Celery on Windows should use `--pool=solo`

## Further documentation

| Document | Topic |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | Runtime and layering |
| [`docs/database-schema.md`](docs/database-schema.md) | Tables and constraints |
| [`docs/double-booking-prevention.md`](docs/double-booking-prevention.md) | GiST exclusion, confirm, reschedule |
| [`docs/leave-conflict-handling.md`](docs/leave-conflict-handling.md) | Leave vs existing bookings |
| [`docs/slot-hold-mechanism.md`](docs/slot-hold-mechanism.md) | Holds and expiry |
| [`docs/notification-failure-handling.md`](docs/notification-failure-handling.md) | Email/calendar retry and idempotency |
| [`docs/llm-prompts.md`](docs/llm-prompts.md) | Gemini prompts and failure isolation |
| [`docs/google-calendar-setup.md`](docs/google-calendar-setup.md) | OAuth console steps |
| [`docs/api-documentation.md`](docs/api-documentation.md) | HTTP API |
| [`docs/testing.md`](docs/testing.md) | QA matrix |
| [`docs/background-jobs.md`](docs/background-jobs.md) | Celery beat schedule |
