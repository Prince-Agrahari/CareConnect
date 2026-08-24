"""Google Calendar implementation of the calendar client protocol."""

from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings
from app.integrations.calendar import CalendarError


def _http_status(exc: HttpError) -> int:
    return int(getattr(exc, "status_code", 0) or getattr(exc.resp, "status", 0) or 0)


def _service(access_token: str, refresh_token: str):
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _calendar_id(calendar_id: str | None) -> str:
    return calendar_id or "primary"


def _update_or_insert(service, calendar_id: str, provider_event_id: str, body: dict) -> dict:
    try:
        return (
            service.events()
            .update(calendarId=calendar_id, eventId=provider_event_id, body=body)
            .execute()
        )
    except HttpError as exc:
        if _http_status(exc) not in {404, 410}:
            raise
    insert_body = {**body, "id": provider_event_id}
    try:
        return service.events().insert(calendarId=calendar_id, body=insert_body).execute()
    except HttpError as exc:
        if _http_status(exc) == 409:
            return {"id": provider_event_id}
        raise


class GoogleCalendarClient:
    def upsert_event(
        self,
        *,
        access_token: str,
        refresh_token: str,
        calendar_id: str | None,
        provider_event_id: str | None,
        title: str,
        start: datetime,
        end: datetime,
        description: str,
    ) -> str:
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        target = _calendar_id(calendar_id)
        try:
            service = _service(access_token, refresh_token)
            if provider_event_id:
                event = _update_or_insert(service, target, provider_event_id, body)
            else:
                event = service.events().insert(calendarId=target, body=body).execute()
            event_id = event.get("id")
            if not event_id:
                raise CalendarError("Google Calendar returned no event id")
            return str(event_id)
        except CalendarError:
            raise
        except HttpError as exc:
            raise CalendarError(str(exc) or "Google Calendar request failed") from exc
        except Exception as exc:
            raise CalendarError(str(exc) or "Google Calendar request failed") from exc

    def delete_event(
        self,
        *,
        access_token: str,
        refresh_token: str,
        calendar_id: str | None,
        provider_event_id: str,
    ) -> None:
        try:
            service = _service(access_token, refresh_token)
            service.events().delete(
                calendarId=_calendar_id(calendar_id),
                eventId=provider_event_id,
            ).execute()
        except HttpError as exc:
            if _http_status(exc) in {404, 410}:
                return
            raise CalendarError(str(exc) or "Google Calendar delete failed") from exc
        except Exception as exc:
            raise CalendarError(str(exc) or "Google Calendar delete failed") from exc
