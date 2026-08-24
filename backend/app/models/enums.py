"""Canonical status and role values stored as constrained strings."""

from enum import StrEnum


class UserRole(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class AppointmentStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    CANCELLED_LEAVE = "cancelled_leave"
    RESCHEDULED = "rescheduled"


class SlotHoldStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CONVERTED = "converted"
    RELEASED = "released"


class DoctorLeaveStatus(StrEnum):
    SCHEDULED = "scheduled"
    PROCESSED = "processed"
    CANCELLED = "cancelled"


class AISummaryStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class UrgencyLevel(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RETRYING = "retrying"


class NotificationChannel(StrEnum):
    EMAIL = "email"


class NotificationType(StrEnum):
    BOOKING_CONFIRMATION = "booking_confirmation"
    APPOINTMENT_REMINDER = "appointment_reminder"
    APPOINTMENT_CANCELLATION = "appointment_cancellation"
    DOCTOR_LEAVE_CANCELLATION = "doctor_leave_cancellation"
    DOCTOR_LEAVE_PROCESSED = "doctor_leave_processed"
    APPOINTMENT_RESCHEDULED = "appointment_rescheduled"
    MEDICATION_REMINDER = "medication_reminder"


class CalendarProvider(StrEnum):
    GOOGLE = "google"


class CalendarSyncStatus(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    DELETED = "deleted"


class MedicationReminderStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


APPOINTMENT_BLOCKING_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.COMPLETED,
)
