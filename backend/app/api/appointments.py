"""Appointment booking routes."""

from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_doctor, get_current_patient, get_current_user
from app.core.clock import utc_now
from app.db.session import get_db
from app.models import User
from app.schemas.appointment import (
    AppointmentCancel,
    AppointmentConfirm,
    AppointmentPublic,
    AppointmentReschedule,
    SlotHoldCreate,
    SlotHoldPublic,
)
from app.schemas.previsit import PrevisitSummaryPublic
from app.schemas.visit import VisitPublic, VisitSubmit
from app.services.appointments import (
    cancel_appointment,
    confirm_appointment,
    get_appointment,
    hold_slot,
    list_appointments,
    reschedule_appointment,
)
from app.services.errors import ServiceError
from app.services.previsit import get_previsit_summary, retry_previsit_summary
from app.services.visit import get_visit, retry_visit_summary, submit_visit

router = APIRouter()


def _raise_service_error(exc: ServiceError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/hold", response_model=SlotHoldPublic, status_code=201)
def create_slot_hold(
    payload: SlotHoldCreate,
    db: Session = Depends(get_db),
    current_patient: User = Depends(get_current_patient),
    now: datetime = Depends(utc_now),
) -> SlotHoldPublic:
    try:
        hold = hold_slot(db, current_patient, payload, now)
    except ServiceError as exc:
        _raise_service_error(exc)
    return SlotHoldPublic.model_validate(hold)


@router.post("/confirm", response_model=AppointmentPublic, status_code=201)
def confirm_held_appointment(
    payload: AppointmentConfirm,
    db: Session = Depends(get_db),
    current_patient: User = Depends(get_current_patient),
    now: datetime = Depends(utc_now),
) -> AppointmentPublic:
    try:
        appointment = confirm_appointment(db, current_patient, payload, now)
    except ServiceError as exc:
        _raise_service_error(exc)
    return AppointmentPublic.model_validate(appointment)


@router.get("", response_model=list[AppointmentPublic])
def read_appointments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AppointmentPublic]:
    try:
        appointments = list_appointments(db, current_user)
    except ServiceError as exc:
        _raise_service_error(exc)
    return [AppointmentPublic.model_validate(item) for item in appointments]


@router.get("/{appointment_id}", response_model=AppointmentPublic)
def read_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AppointmentPublic:
    try:
        appointment = get_appointment(db, current_user, appointment_id)
    except ServiceError as exc:
        _raise_service_error(exc)
    return AppointmentPublic.model_validate(appointment)


@router.get("/{appointment_id}/previsit-summary", response_model=PrevisitSummaryPublic)
def read_previsit_summary(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PrevisitSummaryPublic:
    try:
        return get_previsit_summary(db, current_user, appointment_id)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/{appointment_id}/previsit-summary/retry", response_model=PrevisitSummaryPublic)
def retry_existing_previsit_summary(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    now: datetime = Depends(utc_now),
) -> PrevisitSummaryPublic:
    try:
        return retry_previsit_summary(db, current_user, appointment_id, now)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.get("/{appointment_id}/visit", response_model=VisitPublic)
def read_visit(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VisitPublic:
    try:
        return get_visit(db, current_user, appointment_id)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/{appointment_id}/visit", response_model=VisitPublic, status_code=201)
def create_visit_notes(
    appointment_id: int,
    payload: VisitSubmit,
    db: Session = Depends(get_db),
    current_doctor: User = Depends(get_current_doctor),
    now: datetime = Depends(utc_now),
) -> VisitPublic:
    try:
        return submit_visit(db, current_doctor, appointment_id, payload, now)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/{appointment_id}/visit/summary/retry", response_model=VisitPublic)
def retry_visit_patient_summary(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_doctor: User = Depends(get_current_doctor),
    now: datetime = Depends(utc_now),
) -> VisitPublic:
    try:
        return retry_visit_summary(db, current_doctor, appointment_id, now)
    except ServiceError as exc:
        _raise_service_error(exc)


@router.post("/{appointment_id}/reschedule", response_model=AppointmentPublic, status_code=201)
def reschedule_existing_appointment(
    appointment_id: int,
    payload: AppointmentReschedule,
    db: Session = Depends(get_db),
    current_patient: User = Depends(get_current_patient),
    now: datetime = Depends(utc_now),
) -> AppointmentPublic:
    try:
        appointment = reschedule_appointment(db, current_patient, appointment_id, payload, now)
    except ServiceError as exc:
        _raise_service_error(exc)
    return AppointmentPublic.model_validate(appointment)


@router.post("/{appointment_id}/cancel", response_model=AppointmentPublic)
def cancel_existing_appointment(
    appointment_id: int,
    payload: AppointmentCancel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    now: datetime = Depends(utc_now),
) -> AppointmentPublic:
    try:
        appointment = cancel_appointment(db, current_user, appointment_id, payload, now)
    except ServiceError as exc:
        _raise_service_error(exc)
    return AppointmentPublic.model_validate(appointment)
