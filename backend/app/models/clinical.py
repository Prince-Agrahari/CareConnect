"""Clinical notes, prescriptions, and medication reminder models."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class VisitNote(TimestampMixin, Base):
    __tablename__ = "visit_notes"
    __table_args__ = (
        UniqueConstraint("appointment_id", name="uq_visit_notes_appointment_id"),
        CheckConstraint(
            "summary_status IN ('pending', 'succeeded', 'failed')",
            name="visit_summary_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    clinical_notes: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_instructions: Mapped[str | None] = mapped_column(Text)
    patient_friendly_summary: Mapped[str | None] = mapped_column(Text)
    summary_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    summary_error: Mapped[str | None] = mapped_column(Text)
    summary_raw_response: Mapped[str | None] = mapped_column(Text)
    summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    appointment: Mapped[Appointment] = relationship(back_populates="visit_note")
    doctor: Mapped[DoctorProfile] = relationship()


class Prescription(TimestampMixin, Base):
    __tablename__ = "prescriptions"
    __table_args__ = (UniqueConstraint("appointment_id", name="uq_prescriptions_appointment_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text)

    appointment: Mapped[Appointment] = relationship(back_populates="prescription")
    doctor: Mapped[DoctorProfile] = relationship()
    patient: Mapped[PatientProfile] = relationship()
    medications: Mapped[list[PrescriptionMedication]] = relationship(
        back_populates="prescription",
        cascade="all, delete-orphan",
    )


class PrescriptionMedication(TimestampMixin, Base):
    __tablename__ = "prescription_medications"

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    medicine_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dosage: Mapped[str] = mapped_column(String(128), nullable=False)
    frequency: Mapped[str] = mapped_column(String(128), nullable=False)
    duration: Mapped[str] = mapped_column(String(128), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)

    prescription: Mapped[Prescription] = relationship(back_populates="medications")
    reminders: Mapped[list[MedicationReminder]] = relationship(
        back_populates="medication",
        cascade="all, delete-orphan",
    )


class MedicationReminder(TimestampMixin, Base):
    __tablename__ = "medication_reminders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')",
            name="medication_reminder_status_valid",
        ),
        CheckConstraint("end_date >= start_date", name="reminder_end_on_or_after_start"),
        Index("ix_medication_reminders_next_scheduled_at", "next_scheduled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_medication_id: Mapped[int] = mapped_column(
        ForeignKey("prescription_medications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remind_at: Mapped[time] = mapped_column(Time, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    next_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    medication: Mapped[PrescriptionMedication] = relationship(back_populates="reminders")
    patient: Mapped[PatientProfile] = relationship(back_populates="medication_reminders")
