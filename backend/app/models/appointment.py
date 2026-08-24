"""Appointment, slot hold, symptom, and pre-visit AI summary models."""

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
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import column, literal_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_datetime > start_datetime", name="appointment_end_after_start"),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'completed', 'cancelled', "
            "'cancelled_leave', 'rescheduled')",
            name="appointment_status_valid",
        ),
        Index("ix_appointments_doctor_start", "doctor_id", "start_datetime"),
        Index("ix_appointments_patient_start", "patient_id", "start_datetime"),
        Index("ix_appointments_status", "status"),
        ExcludeConstraint(
            (column("doctor_id"), "="),
            (literal_column("tstzrange(start_datetime, end_datetime, '[)')"), "&&"),
            using="gist",
            where=text("status IN ('pending', 'confirmed', 'completed')"),
            name="ex_appointments_doctor_overlap",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="confirmed")
    reason: Mapped[str | None] = mapped_column(Text)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rescheduled_from_appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"),
        index=True,
    )

    patient: Mapped[PatientProfile] = relationship(
        back_populates="appointments",
        foreign_keys=[patient_id],
    )
    doctor: Mapped[DoctorProfile] = relationship(
        back_populates="appointments",
        foreign_keys=[doctor_id],
    )
    rescheduled_from: Mapped[Appointment | None] = relationship(
        remote_side="Appointment.id",
        foreign_keys=[rescheduled_from_appointment_id],
    )
    symptom_submission: Mapped[SymptomSubmission | None] = relationship(
        back_populates="appointment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    visit_note: Mapped[VisitNote | None] = relationship(
        back_populates="appointment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    prescription: Mapped[Prescription | None] = relationship(
        back_populates="appointment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    calendar_events: Mapped[list[CalendarEvent]] = relationship(back_populates="appointment")
    notification_logs: Mapped[list[NotificationLog]] = relationship(back_populates="appointment")


class AppointmentSlotHold(TimestampMixin, Base):
    __tablename__ = "appointment_slot_holds"
    __table_args__ = (
        CheckConstraint("end_datetime > start_datetime", name="hold_end_after_start"),
        CheckConstraint(
            "status IN ('active', 'expired', 'converted', 'released')",
            name="hold_status_valid",
        ),
        CheckConstraint("expires_at > created_at", name="hold_expires_after_create"),
        Index("ix_slot_holds_doctor_start", "doctor_id", "start_datetime"),
        Index("ix_slot_holds_expires_at", "expires_at"),
        ExcludeConstraint(
            (column("doctor_id"), "="),
            (literal_column("tstzrange(start_datetime, end_datetime, '[)')"), "&&"),
            using="gist",
            where=text("status = 'active'"),
            name="ex_slot_holds_doctor_overlap",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    patient: Mapped[PatientProfile] = relationship(
        back_populates="slot_holds",
        foreign_keys=[patient_id],
    )
    doctor: Mapped[DoctorProfile] = relationship(
        back_populates="slot_holds",
        foreign_keys=[doctor_id],
    )


class SymptomSubmission(TimestampMixin, Base):
    __tablename__ = "symptom_submissions"
    __table_args__ = (UniqueConstraint("appointment_id", name="uq_symptom_submissions_appointment_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    symptoms: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    appointment: Mapped[Appointment] = relationship(back_populates="symptom_submission")
    patient: Mapped[PatientProfile] = relationship(back_populates="symptom_submissions")
    ai_summary: Mapped[AISymptomSummary | None] = relationship(
        back_populates="symptom_submission",
        uselist=False,
        cascade="all, delete-orphan",
    )


class AISymptomSummary(TimestampMixin, Base):
    __tablename__ = "ai_symptom_summaries"
    __table_args__ = (
        UniqueConstraint(
            "symptom_submission_id",
            name="uq_ai_symptom_summaries_submission_id",
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ai_summary_status_valid",
        ),
        CheckConstraint(
            "urgency_level IS NULL OR urgency_level IN ('Low', 'Medium', 'High')",
            name="urgency_level_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symptom_submission_id: Mapped[int] = mapped_column(
        ForeignKey("symptom_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    urgency_level: Mapped[str | None] = mapped_column(String(16))
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    suggested_questions: Mapped[list | None] = mapped_column(JSONB)
    raw_response: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    symptom_submission: Mapped[SymptomSubmission] = relationship(back_populates="ai_summary")
