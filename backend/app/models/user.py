"""User and patient profile models."""

from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import UserRole
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('patient', 'doctor', 'admin')",
            name="role_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    patient_profile: Mapped[PatientProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    doctor_profile: Mapped[DoctorProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    calendar_integration: Mapped[CalendarIntegration | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    notification_logs: Mapped[list[NotificationLog]] = relationship(back_populates="user")

    def is_patient(self) -> bool:
        return self.role == UserRole.PATIENT

    def is_doctor(self) -> bool:
        return self.role == UserRole.DOCTOR

    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


class PatientProfile(TimestampMixin, Base):
    __tablename__ = "patient_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_patient_profiles_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(String(32))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(255))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32))

    user: Mapped[User] = relationship(back_populates="patient_profile")
    appointments: Mapped[list[Appointment]] = relationship(
        back_populates="patient",
        foreign_keys="Appointment.patient_id",
    )
    slot_holds: Mapped[list[AppointmentSlotHold]] = relationship(
        back_populates="patient",
        foreign_keys="AppointmentSlotHold.patient_id",
    )
    symptom_submissions: Mapped[list[SymptomSubmission]] = relationship(back_populates="patient")
    medication_reminders: Mapped[list[MedicationReminder]] = relationship(back_populates="patient")
