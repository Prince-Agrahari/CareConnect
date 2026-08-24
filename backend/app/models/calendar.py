"""Google Calendar integration and event sync models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class CalendarIntegration(TimestampMixin, Base):
    __tablename__ = "calendar_integrations"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_calendar_integrations_user_provider"),
        CheckConstraint("provider IN ('google')", name="calendar_provider_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="google")
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_calendar_id: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[str | None] = mapped_column(Text)
    is_connected: Mapped[bool] = mapped_column(default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="calendar_integration")
    events: Mapped[list[CalendarEvent]] = relationship(
        back_populates="integration",
        cascade="all, delete-orphan",
    )


class CalendarEvent(TimestampMixin, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint(
            "appointment_id",
            "user_id",
            name="uq_calendar_events_appointment_user",
        ),
        Index(
            "uq_calendar_events_provider_event",
            "calendar_integration_id",
            "provider_event_id",
            unique=True,
            postgresql_where=text("provider_event_id IS NOT NULL"),
        ),
        CheckConstraint(
            "sync_status IN ('pending', 'synced', 'failed', 'deleted')",
            name="calendar_sync_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    calendar_integration_id: Mapped[int] = mapped_column(
        ForeignKey("calendar_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_event_id: Mapped[str | None] = mapped_column(String(255))
    sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    appointment: Mapped[Appointment] = relationship(back_populates="calendar_events")
    user: Mapped[User] = relationship()
    integration: Mapped[CalendarIntegration] = relationship(back_populates="events")
