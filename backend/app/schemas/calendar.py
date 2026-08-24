"""Pydantic schemas for Google Calendar connection. Tokens are never included."""

from pydantic import BaseModel, ConfigDict


class CalendarConnectResponse(BaseModel):
    authorization_url: str
    provider: str = "google"


class CalendarStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    connected: bool
    provider: str = "google"
    google_calendar_id: str | None = None
