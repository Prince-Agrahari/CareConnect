"""Public doctor catalog and availability. Slots are generated on the server."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.session import get_db
from app.schemas.availability import AvailabilityResponse
from app.schemas.doctor import DoctorCatalogPublic, WorkingHoursPublic
from app.services.availability import get_doctor_availability
from app.services.doctors import get_doctor_or_404, list_catalog_doctors
from app.services.errors import ServiceError

router = APIRouter()


def to_doctor_catalog(doctor) -> DoctorCatalogPublic:
    hours = sorted(doctor.working_hours, key=lambda item: (item.day_of_week, item.start_time))
    user_active = doctor.user.is_active if doctor.user is not None else False
    return DoctorCatalogPublic(
        id=doctor.id,
        full_name=doctor.user.full_name if doctor.user is not None else "",
        specialization=doctor.specialization,
        qualification=doctor.qualification,
        bio=doctor.bio,
        slot_duration_minutes=doctor.slot_duration_minutes,
        is_active=bool(doctor.is_active and user_active),
        working_hours=[WorkingHoursPublic.model_validate(item) for item in hours],
    )


@router.get("", response_model=list[DoctorCatalogPublic])
def list_public_doctors(
    specialization: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[DoctorCatalogPublic]:
    return [to_doctor_catalog(doctor) for doctor in list_catalog_doctors(db, specialization)]


@router.get("/{doctor_id}", response_model=DoctorCatalogPublic)
def read_public_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
) -> DoctorCatalogPublic:
    try:
        doctor = get_doctor_or_404(db, doctor_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return to_doctor_catalog(doctor)


@router.get("/{doctor_id}/availability", response_model=AvailabilityResponse)
def read_doctor_availability(
    doctor_id: int,
    query_date: date = Query(..., alias="date", description="Calendar date in YYYY-MM-DD"),
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
) -> AvailabilityResponse:
    try:
        return get_doctor_availability(db, doctor_id, query_date, now)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
