# Google Calendar setup

CareConnect syncs confirmed appointments to Google Calendar for patients and doctors who connect their account. OAuth tokens stay on the server and are never returned by the API or committed to git.

## 1. Create a Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (for example `careconnect-dev`).
3. Select that project for the remaining steps.

## 2. Enable the Calendar API

1. Go to **APIs & Services → Library**.
2. Search for **Google Calendar API**.
3. Click **Enable**.

## 3. Configure the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** for local development (or **Internal** on a Google Workspace org).
3. App name: `CareConnect`.
4. Add an authorized support email.
5. Scopes: `https://www.googleapis.com/auth/calendar.events` (see, edit, share, and permanently delete events).
6. Add test users (your Gmail addresses) while the app is in Testing.

Do not request scopes you do not use.

## 4. Create OAuth credentials

1. Go to **APIs & Services → Credentials**.
2. **Create credentials → OAuth client ID**.
3. Application type: **Web application**.
4. Name: `CareConnect local`.
5. Authorized redirect URIs — add exactly:

   `http://localhost:8000/api/v1/calendar/callback`

6. Copy the **Client ID** and **Client secret**.

Never commit the client secret. Do not put it in source, screenshots in the repo, or `.env` files that are checked in.

## 5. Environment variables

Copy `.env.example` to `.env` (already gitignored) and set:

```
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/calendar/callback
GOOGLE_OAUTH_SUCCESS_REDIRECT=http://localhost:5173/?calendar=connected
GOOGLE_OAUTH_FAILURE_REDIRECT=http://localhost:5173/?calendar=error
```

`GOOGLE_REDIRECT_URI` must match the Cloud Console redirect URI character-for-character, including scheme and port.

## 6. Connect a CareConnect user

1. Start the API (`uvicorn app.main:app --reload`) and the frontend (`npm run dev`).
2. Sign in as a patient or doctor.
3. Open **Calendar** in the portal (`/patient/calendar` or `/doctor/calendar`) and connect, or call `GET /api/v1/calendar/connect` with a Bearer JWT.
4. The API returns `authorization_url`. Google redirects to `/api/v1/calendar/callback`.
5. The callback stores tokens, then redirects to `GOOGLE_OAUTH_SUCCESS_REDIRECT` (default `http://localhost:5173/?calendar=connected`). The home page forwards signed-in users to their portal calendar view.
6. `GET /api/v1/calendar/status` returns `{ "connected": true, "provider": "google" }` with **no tokens**.
7. `POST /api/v1/calendar/disconnect` clears tokens and marks the integration disconnected.

If Google omits a refresh token, disconnect and reconnect so the consent screen can issue offline access (`prompt=consent`, `access_type=offline`).

## Sync behaviour

| Appointment action | Calendar action |
| --- | --- |
| Confirm | Create events for the patient and the doctor when each has connected Google Calendar |
| Reschedule | Update the existing Google event times (same external event id) |
| Cancel or doctor leave | Delete the Google events |

Rows live in `calendar_events`: `provider_event_id` (external event ID), `sync_status` (`pending` / `synced` / `failed` / `deleted`), `last_error`, `last_synced_at`. Unique `(appointment_id, user_id)` and unique provider event ids prevent duplicates on retry.

Calendar API failures are stored on the event row. They never roll back appointment confirm, reschedule, or cancel.

Expired access tokens are refreshed with the stored refresh token before Calendar API calls.

Retry, unique event keys, and failure isolation are described in `docs/notification-failure-handling.md`.
