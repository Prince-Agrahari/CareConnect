"""Doctor profile, working hours, and leave models."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import column, literal_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class DoctorProfile(TimestampMixin, Base):
    __tablename__ = "doctor_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_doctor_profiles_user_id"),
        CheckConstraint("slot_duration_minutes > 0", name="slot_duration_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    specialization: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    qualification: Mapped[str | None] = mapped_column(String(255))
    bio: Mapped[str | None] = mapped_column(Text)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    user: Mapped[User] = relationship(back_populates="doctor_profile")
    working_hours: Mapped[list[DoctorWorkingHours]] = relationship(
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
    leaves: Mapped[list[DoctorLeave]] = relationship(
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
    appointments: Mapped[list[Appointment]] = relationship(
        back_populates="doctor",
        foreign_keys="Appointment.doctor_id",
    )
    slot_holds: Mapped[list[AppointmentSlotHold]] = relationship(
        back_populates="doctor",
        foreign_keys="AppointmentSlotHold.doctor_id",
    )


class DoctorWorkingHours(TimestampMixin, Base):
    __tablename__ = "doctor_working_hours"
    __table_args__ = (
        UniqueConstraint(
            "doctor_id",
            "day_of_week",
            "start_time",
            name="uq_doctor_working_hours_shift",
        ),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="day_of_week_range"),
        CheckConstraint("end_time > start_time", name="hours_end_after_start"),
        ExcludeConstraint(
            (column("doctor_id"), "="),
            (column("day_of_week"), "="),
            (
                literal_column(
                    "tsrange((DATE '2000-01-01' + start_time), "
                    "(DATE '2000-01-01' + end_time), '[)')"
                ),
                "&&",
            ),
            using="gist",
            name="ex_doctor_working_hours_no_overlap",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    doctor: Mapped[DoctorProfile] = relationship(back_populates="working_hours")


class DoctorLeave(TimestampMixin, Base):
    __tablename__ = "doctor_leaves"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'processed', 'cancelled')",
            name="leave_status_valid",
        ),
        CheckConstraint("end_date >= start_date", name="leave_end_on_or_after_start"),
        ExcludeConstraint(
            (column("doctor_id"), "="),
            (literal_column("daterange(start_date, end_date, '[]')"), "&&"),
            using="gist",
            where=text("status <> 'cancelled'"),
            name="ex_doctor_leaves_no_overlap",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled", index=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    doctor: Mapped[DoctorProfile] = relationship(back_populates="leaves")
    created_by_admin: Mapped[User | None] = relationship(foreign_keys=[created_by_admin_id])
