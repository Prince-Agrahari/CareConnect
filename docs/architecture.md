# Architecture

CareConnect is a three-portal healthcare appointment system: a React single-page app, a FastAPI API, PostgreSQL as the system of record, and Celery workers for email and calendar work that must not roll back clinical data.

## Runtime view

```
Browser (patient / doctor / admin)
        │  HTTPS or local http://localhost:5173
        ▼
React + Vite  (Tailwind CSS, React Router, Axios)
        │  JSON + Bearer JWT  →  VITE_API_URL (default http://localhost:8000)
        ▼
FastAPI  (uvicorn)
        │
        ├── PostgreSQL  (appointments, holds, users, clinical rows, notification_logs, calendar_events)
        │
        ├── Gemini      (in-process, after the booking/visit transaction commits; 30s timeout)
        │
        └── enqueue (best-effort)
                ▼
           Redis broker
                ▼
        Celery worker + Celery beat
                ├── SendGrid  (email)
                └── Google Calendar API  (create / update / delete events)
```

The browser never talks to Gemini, SendGrid, or Google. OAuth tokens and API keys stay on the server.

## Request path vs background path

| Work | When it runs | Failure effect |
| --- | --- | --- |
| Auth, availability, hold, confirm, cancel, reschedule, leave, visit notes | Inside the HTTP request and a PostgreSQL transaction | HTTP error; transaction rolls back |
| Pre-visit and post-visit Gemini summaries | After commit, still in the HTTP request | Summary row marked `failed`; appointment/notes stay saved |
| Booking, reminder, cancellation, leave, and medication emails | Celery, after commit | `notification_logs` retry; appointment stays saved |
| Google Calendar create / update / delete | Celery, after commit | `calendar_events.sync_status = failed`; appointment stays saved |

`enqueue_task` swallows broker errors. If Redis is down during the HTTP request, the database row remains `pending` and Celery beat later dispatches it. See `docs/notification-failure-handling.md` and `docs/background-jobs.md`.

## Layers (backend)

| Layer | Location | Responsibility |
| --- | --- | --- |
| HTTP routers | `backend/app/api/` | Auth, validation, status codes. No overlap logic. |
| Dependencies | `backend/app/api/deps.py` | Load the user from JWT `sub`, then check the **database** role |
| Services | `backend/app/services/` | Transactions, `FOR UPDATE`, availability, leave, notifications |
| Models | `backend/app/models/` | Schema, check constraints, GiST exclusion constraints |
| Schemas | `backend/app/schemas/` | Pydantic request/response models |
| Integrations | `backend/app/integrations/` | `LLMClient`, `EmailClient`, `CalendarClient` protocols and adapters |
| Tasks | `backend/app/tasks/` | Celery entrypoints that call services |

Appointment services do not import SendGrid, Google client libraries, or Gemini. They call protocols. Tests replace those clients with fakes.

## Frontend

| Piece | Location | Responsibility |
| --- | --- | --- |
| Routes | `frontend/src/App.jsx` | `/patient`, `/doctor`, `/admin` trees |
| Route guards | `frontend/src/components/ProtectedRoute.jsx` | Navigation only |
| API client | `frontend/src/api/client.js` | Axios, `Authorization: Bearer`, 401 logout |
| Auth state | `frontend/src/context/AuthContext.jsx` | Token in `localStorage` key `careconnect_token` |

Route guards are not authorization. Every mutating API call is authorized again on the server from the database role.

## Booking pipeline

1. `GET /api/doctors/{id}/availability?date=` — server-generated slots (hours, duration, leave, holds, visits, current time).
2. `POST /api/appointments/hold` — 5-minute hold (`SLOT_HOLD_MINUTES`). `expires_at` is stored in PostgreSQL.
3. `POST /api/appointments/confirm` — one transaction: lock doctor, expire stale holds, re-check slots, insert `confirmed` appointment, store symptoms, convert hold.
4. After commit: Gemini pre-visit summary, then enqueue email and calendar jobs.

PostgreSQL exclusion constraints are the last line of defence against double-booking. See `docs/double-booking-prevention.md` and `docs/slot-hold-mechanism.md`.

## Trust boundaries

- Passwords are bcrypt hashes. JWTs are HS256, default 30-minute expiry.
- The JWT may include a `role` claim for display; `get_current_user` uses `sub` only and reloads the user. Admin access requires `users.role = admin` in PostgreSQL.
- Public registration always creates a patient. `role` in the register body is ignored (`extra="ignore"`).
- Doctor and admin accounts are not self-serve.
- Calendar OAuth tokens are stored on `calendar_integrations` and are never returned by `/status` or `/connect`.
- `APP_ENV=production` refuses the placeholder `JWT_SECRET_KEY`.
