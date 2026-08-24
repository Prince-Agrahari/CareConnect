"""Pydantic schemas for doctor visit notes and prescriptions."""

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.appointment import AppointmentPublic


class MedicationCreate(BaseModel):
    medicine_name: str = Field(min_length=1, max_length=255)
    dosage: str = Field(min_length=1, max_length=128)
    frequency: str = Field(min_length=1, max_length=128)
    duration: str = Field(min_length=1, max_length=128)
    instructions: str | None = Field(default=None, max_length=2000)

    @field_validator("medicine_name", "dosage", "frequency", "duration")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("this field is required")
        return stripped

    @field_validator("instructions")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class MedicationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    medicine_name: str
    dosage: str
    frequency: str
    duration: str
    instructions: str | None


class MedicationReminderPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    medicine_name: str
    dosage: str
    frequency: str
    duration: str
    instructions: str | None
    remind_at: time
    start_date: date
    end_date: date
    next_scheduled_at: datetime | None
    status: str


class VisitSubmit(BaseModel):
    clinical_notes: str = Field(min_length=1, max_length=20000)
    follow_up_instructions: str | None = Field(default=None, max_length=5000)
    medications: list[MedicationCreate] = Field(default_factory=list)

    @field_validator("clinical_notes")
    @classmethod
    def notes_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("clinical notes are required")
        return stripped

    @field_validator("follow_up_instructions")
    @classmethod
    def strip_follow_up(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class VisitPublic(BaseModel):
    appointment: AppointmentPublic
    symptoms: str | None = None
    urgency_level: str | None = None
    chief_complaint: str | None = None
    suggested_questions: list[str] | None = None
    previsit_status: str | None = None
    clinical_notes: str | None = None
    follow_up_instructions: str | None = None
    medications: list[MedicationPublic] = Field(default_factory=list)
    patient_friendly_summary: str | None = None
    summary_status: str | None = None
    summary_error: str | None = None
    summary_generated_at: datetime | None = None
    summary_raw_response: str | None = None
    is_ai_generated: bool = False
    disclaimer: str = (
        "This summary is AI-generated, assistive only, and is not a medical diagnosis."
    )
