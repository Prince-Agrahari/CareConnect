"""Pydantic schemas for admin doctor management."""

from datetime import date, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

MIN_SLOT_DURATION_MINUTES = 5
MAX_SLOT_DURATION_MINUTES = 180


class WorkingHoursIn(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0 = Monday … 6 = Sunday")
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def start_before_end(self) -> "WorkingHoursIn":
        if self.start_time >= self.end_time:
            raise ValueError("start time must be before end time")
        return self


class WorkingHoursPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    day_of_week: int
    start_time: time
    end_time: time


class WorkingHoursReplace(BaseModel):
    hours: list[WorkingHoursIn]


class DoctorLeaveIn(BaseModel):
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def end_on_or_after_start(self) -> "DoctorLeaveIn":
        if self.end_date < self.start_date:
            raise ValueError("end date must be on or after start date")
        return self


class DoctorLeavePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    start_date: date
    end_date: date
    reason: str | None
    status: str


class DoctorLeaveCreateResponse(DoctorLeavePublic):
    cancelled_appointment_ids: list[int]


class DoctorCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=255)
    specialization: str = Field(min_length=1, max_length=128)
    qualification: str | None = Field(default=None, max_length=255)
    bio: str | None = None
    slot_duration_minutes: int = Field(
        default=30,
        ge=MIN_SLOT_DURATION_MINUTES,
        le=MAX_SLOT_DURATION_MINUTES,
    )
    is_active: bool = True
    working_hours: list[WorkingHoursIn] = Field(default_factory=list)


class DoctorUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    specialization: str | None = Field(default=None, min_length=1, max_length=128)
    qualification: str | None = Field(default=None, max_length=255)
    bio: str | None = None
    slot_duration_minutes: int | None = Field(
        default=None,
        ge=MIN_SLOT_DURATION_MINUTES,
        le=MAX_SLOT_DURATION_MINUTES,
    )
    is_active: bool | None = None


class DoctorCatalogPublic(BaseModel):
    id: int
    full_name: str
    specialization: str
    qualification: str | None
    bio: str | None
    slot_duration_minutes: int
    is_active: bool
    working_hours: list[WorkingHoursPublic]


class DoctorPublic(BaseModel):
    id: int
    user_id: int
    email: str
    full_name: str
    specialization: str
    qualification: str | None
    bio: str | None
    slot_duration_minutes: int
    is_active: bool
    working_hours: list[WorkingHoursPublic]
    leaves: list[DoctorLeavePublic]
