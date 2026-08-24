"""Pydantic schemas for pre-visit symptoms and AI summaries."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PrevisitSummaryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appointment_id: int
    symptoms: str
    submitted_at: datetime
    urgency_level: str | None
    chief_complaint: str | None
    suggested_questions: list[str] | None
    status: str
    error_message: str | None
    generated_at: datetime | None
    raw_response: str | None = None
    disclaimer: str = "This summary is assistive only and is not a medical diagnosis."
