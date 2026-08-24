"""Pydantic schemas for appointment booking."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SlotHoldCreate(BaseModel):
    doctor_id: int
    start_datetime: datetime
    end_datetime: datetime

    @model_validator(mode="after")
    def end_after_start(self) -> "SlotHoldCreate":
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime must be after start_datetime")
        return self


class SlotHoldPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    start_datetime: datetime
    end_datetime: datetime
    expires_at: datetime
    status: str


class AppointmentConfirm(BaseModel):
    hold_id: int
    symptoms: str = Field(min_length=1, max_length=10000)
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("symptoms")
    @classmethod
    def symptoms_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("symptoms are required before confirmation")
        return stripped


class AppointmentCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class AppointmentReschedule(BaseModel):
    hold_id: int


class AppointmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    doctor_id: int
    start_datetime: datetime
    end_datetime: datetime
    status: str
    reason: str | None
    cancellation_reason: str | None
    cancelled_at: datetime | None
    rescheduled_from_appointment_id: int | None = None
    patient_name: str | None = None
    doctor_name: str | None = None
    doctor_specialization: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="wrap")
    @classmethod
    def populate_related_names(cls, data: object, handler):
        validated = handler(data)
        patient = getattr(data, "patient", None)
        doctor = getattr(data, "doctor", None)
        if patient is None and doctor is None:
            return validated
        patient_user = getattr(patient, "user", None) if patient is not None else None
        doctor_user = getattr(doctor, "user", None) if doctor is not None else None
        return validated.model_copy(
            update={
                "patient_name": getattr(patient_user, "full_name", None) or validated.patient_name,
                "doctor_name": getattr(doctor_user, "full_name", None) or validated.doctor_name,
                "doctor_specialization": getattr(doctor, "specialization", None)
                or validated.doctor_specialization,
            }
        )
