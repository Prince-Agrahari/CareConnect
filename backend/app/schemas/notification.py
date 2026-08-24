"""Notification log schemas for admin monitoring. Tokens are never included."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationLogPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    appointment_id: int | None
    notification_type: str
    channel: str
    recipient: str
    subject: str
    status: str
    error_message: str | None
    retry_count: int
    last_attempt_at: datetime | None
    sent_at: datetime | None
    created_at: datetime
