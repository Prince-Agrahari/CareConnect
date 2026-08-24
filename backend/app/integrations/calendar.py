"""Calendar client abstraction. Sync jobs must not import Google APIs directly."""

from datetime import datetime
from typing import Protocol, runtime_checkable


class CalendarError(Exception):
    """Raised when a calendar provider call fails. Callers must not cancel appointments."""


@runtime_checkable
class CalendarClient(Protocol):
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
        """Create or update an event. Returns the provider event id."""

    def delete_event(
        self,
        *,
        access_token: str,
        refresh_token: str,
        calendar_id: str | None,
        provider_event_id: str,
    ) -> None:
        """Delete an event. Missing events are not an error."""


_override_client: CalendarClient | None = None


def set_calendar_client(client: CalendarClient | None) -> None:
    global _override_client
    _override_client = client


def get_calendar_client() -> CalendarClient:
    if _override_client is not None:
        return _override_client
    from app.integrations.google_calendar import GoogleCalendarClient

    return GoogleCalendarClient()
