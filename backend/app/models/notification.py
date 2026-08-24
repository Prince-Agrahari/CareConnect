"""Notification log model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class NotificationLog(TimestampMixin, Base):
    __tablename__ = "notification_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'retrying')",
            name="notification_status_valid",
        ),
        CheckConstraint("channel IN ('email')", name="notification_channel_valid"),
        CheckConstraint("retry_count >= 0", name="notification_retry_count_non_negative"),
        UniqueConstraint("idempotency_key", name="uq_notification_logs_idempotency_key"),
        Index("ix_notification_logs_status", "status"),
        Index("ix_notification_logs_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"),
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="email")
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="notification_logs")
    appointment: Mapped[Appointment | None] = relationship(back_populates="notification_logs")
