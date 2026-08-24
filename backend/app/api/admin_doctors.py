"""Admin REST APIs for doctor management."""

from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.clock import utc_now
from app.db.session import get_db
from app.models import DoctorProfile, User
from app.schemas.doctor import (
    DoctorCreate,
    DoctorLeaveCreateResponse,
    DoctorLeaveIn,
    DoctorLeavePublic,
    DoctorPublic,
    DoctorUpdate,
    WorkingHoursPublic,
    WorkingHoursReplace,
)
from app.services.doctors import (
    create_doctor,
    create_doctor_leave,
    get_doctor_or_404,
    list_doctors,
    replace_working_hours,
    set_doctor_active,
    update_doctor,
)
from app.services.errors import ServiceError

router = APIRouter()


def _raise_service_error(exc: ServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def to_doctor_public(doctor: DoctorProfile) -> DoctorPublic:
    hours = sorted(doctor.working_hours, key=lambda item: (item.day_of_week, item.start_time))
    leaves = sorted(doctor.leaves, key=lambda item: (item.start_date, item.id))
    return DoctorPublic(
        id=doctor.id,
        user_id=doctor.user_id,
        email=doctor.user.email,
        full_name=doctor.user.full_name,
        specialization=doctor.specialization,
        qualification=doctor.qualification,
        bio=doctor.bio,
        slot_duration_minutes=doctor.slot_duration_minutes,
        is_active=doctor.is_active,
        working_hours=[WorkingHoursPublic.model_validate(item) for item in hours],
        leaves=[DoctorLeavePublic.model_validate(item) for item in leaves],
    )


@router.post("", response_model=DoctorPublic, status_code=201)
def admin_create_doctor(
    payload: DoctorCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> DoctorPublic:
    try:
        doctor = create_doctor(db, payload)
    except ServiceError as exc:
        _raise_service_error(exc)
    return to_doctor_public(doctor)


@router.get("", response_model=list[DoctorPublic])
def admin_list_doctors(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> list[DoctorPublic]:
    return [to_doctor_public(doctor) for doctor in list_doctors(db)]


@router.get("/{doctor_id}", response_model=DoctorPublic)
def admin_get_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> DoctorPublic:
    try:
        doctor = get_doctor_or_404(db, doctor_id)
    except ServiceError as exc:
        _raise_service_error(exc)
    return to_doctor_public(doctor)


@router.patch("/{doctor_id}", response_model=DoctorPublic)
def admin_update_doctor(
    doctor_id: int,
    payload: DoctorUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> DoctorPublic:
    try:
        doctor = update_doctor(db, doctor_id, payload)
    except ServiceError as exc:
        _raise_service_error(exc)
    return to_doctor_public(doctor)


@router.post("/{doctor_id}/activate", response_model=DoctorPublic)
def admin_activate_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> DoctorPublic:
    try:
        doctor = set_doctor_active(db, doctor_id, True)
    except ServiceError as exc:
        _raise_service_error(exc)
    return to_doctor_public(doctor)


@router.post("/{doctor_id}/deactivate", response_model=DoctorPublic)
def admin_deactivate_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> DoctorPublic:
    try:
        doctor = set_doctor_active(db, doctor_id, False)
    except ServiceError as exc:
        _raise_service_error(exc)
    return to_doctor_public(doctor)


@router.put("/{doctor_id}/working-hours", response_model=DoctorPublic)
def admin_replace_working_hours(
    doctor_id: int,
    payload: WorkingHoursReplace,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> DoctorPublic:
    try:
        doctor = replace_working_hours(db, doctor_id, payload.hours)
    except ServiceError as exc:
        _raise_service_error(exc)
    return to_doctor_public(doctor)


@router.post("/{doctor_id}/leave", response_model=DoctorLeaveCreateResponse, status_code=201)
@router.post("/{doctor_id}/leaves", response_model=DoctorLeaveCreateResponse, status_code=201)
def admin_create_doctor_leave(
    doctor_id: int,
    payload: DoctorLeaveIn,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
    now: datetime = Depends(utc_now),
) -> DoctorLeaveCreateResponse:
    try:
        leave, cancelled_ids = create_doctor_leave(
            db,
            doctor_id,
            payload,
            current_admin.id,
            now,
        )
    except ServiceError as exc:
        _raise_service_error(exc)
    public = DoctorLeavePublic.model_validate(leave)
    return DoctorLeaveCreateResponse(
        **public.model_dump(),
        cancelled_appointment_ids=cancelled_ids,
    )
