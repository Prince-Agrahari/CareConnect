"""Appointment hold, confirm, list, cancel, and reschedule services."""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import Appointment, AppointmentSlotHold, DoctorProfile, PatientProfile, SymptomSubmission, User
from app.models.enums import AppointmentStatus, SlotHoldStatus, UserRole
from app.schemas.appointment import AppointmentCancel, AppointmentConfirm, AppointmentReschedule, SlotHoldCreate
from app.services.availability import _as_utc, get_doctor_availability
from app.services.doctors import DOCTOR_LOAD_OPTIONS, ensure_doctor_can_accept_bookings
from app.services.errors import ServiceError

APPOINTMENT_LOAD_OPTIONS = (
    selectinload(Appointment.patient).selectinload(PatientProfile.user),
    selectinload(Appointment.doctor).selectinload(DoctorProfile.user),
)


def _conflict(detail: str) -> ServiceError:
    return ServiceError(status_code=409, detail=detail)


def require_patient_profile(user: User) -> PatientProfile:
    if user.patient_profile is None:
        raise ServiceError(status_code=403, detail="Patient access required")
    return user.patient_profile


def require_doctor_profile(user: User) -> DoctorProfile:
    if user.doctor_profile is None:
        raise ServiceError(status_code=403, detail="Doctor access required")
    return user.doctor_profile


_MUTATING_STATUSES = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}


def _lock_doctor(db: Session, doctor_id: int) -> DoctorProfile:
    doctor = db.scalar(
        select(DoctorProfile)
        .where(DoctorProfile.id == doctor_id)
        .options(*DOCTOR_LOAD_OPTIONS)
        .with_for_update()
    )
    if doctor is None:
        raise ServiceError(status_code=404, detail="Doctor not found")
    return doctor


def _lock_appointment(db: Session, appointment_id: int) -> Appointment:
    appointment = db.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .options(*APPOINTMENT_LOAD_OPTIONS)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if appointment is None:
        raise ServiceError(status_code=404, detail="Appointment not found")
    return appointment


def _expire_stale_holds(db: Session, doctor_id: int, now: datetime) -> None:
    db.execute(
        update(AppointmentSlotHold)
        .where(
            AppointmentSlotHold.doctor_id == doctor_id,
            AppointmentSlotHold.status == SlotHoldStatus.ACTIVE,
            AppointmentSlotHold.expires_at <= now,
        )
        .values(status=SlotHoldStatus.EXPIRED)
    )
    db.flush()


def _slot_is_available(
    db: Session,
    doctor_id: int,
    start: datetime,
    end: datetime,
    now: datetime,
    ignore_hold_id: int | None = None,
) -> bool:
    availability = get_doctor_availability(
        db,
        doctor_id,
        start.date(),
        now,
        ignore_hold_id=ignore_hold_id,
    )
    return any(
        slot.start_datetime == start and slot.end_datetime == end for slot in availability.slots
    )


def _is_hold_expired(hold: AppointmentSlotHold, now: datetime) -> bool:
    return hold.status != SlotHoldStatus.ACTIVE or hold.expires_at <= now


def hold_slot(
    db: Session,
    patient: User,
    payload: SlotHoldCreate,
    now: datetime,
) -> AppointmentSlotHold:
    profile = require_patient_profile(patient)
    start = _as_utc(payload.start_datetime)
    end = _as_utc(payload.end_datetime)
    doctor = _lock_doctor(db, payload.doctor_id)
    ensure_doctor_can_accept_bookings(doctor)
    _expire_stale_holds(db, doctor.id, now)
    if not _slot_is_available(db, doctor.id, start, end, now):
        raise _conflict("Slot is no longer available")

    hold = AppointmentSlotHold(
        patient_id=profile.id,
        doctor_id=doctor.id,
        start_datetime=start,
        end_datetime=end,
        expires_at=now + timedelta(minutes=settings.SLOT_HOLD_MINUTES),
        status=SlotHoldStatus.ACTIVE,
    )
    db.add(hold)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict("Slot is no longer available") from exc
    db.refresh(hold)
    return hold


def confirm_appointment(
    db: Session,
    patient: User,
    payload: AppointmentConfirm,
    now: datetime,
) -> Appointment:
    profile = require_patient_profile(patient)
    hold = db.get(AppointmentSlotHold, payload.hold_id)
    if hold is None:
        raise ServiceError(status_code=404, detail="Slot hold not found")
    if hold.patient_id != profile.id:
        raise ServiceError(status_code=403, detail="You can only confirm your own slot hold")

    doctor = _lock_doctor(db, hold.doctor_id)
    ensure_doctor_can_accept_bookings(doctor)
    _expire_stale_holds(db, doctor.id, now)
    db.refresh(hold)

    if _is_hold_expired(hold, now):
        if hold.status == SlotHoldStatus.ACTIVE:
            hold.status = SlotHoldStatus.EXPIRED
            db.commit()
        raise _conflict("Slot hold has expired")
    if hold.status != SlotHoldStatus.ACTIVE:
        raise _conflict("Slot hold is no longer active")
    if not _slot_is_available(
        db,
        doctor.id,
        hold.start_datetime,
        hold.end_datetime,
        now,
        ignore_hold_id=hold.id,
    ):
        raise _conflict("Slot is no longer available")

    from app.services.previsit import generate_previsit_summary, save_symptoms_pending

    appointment = Appointment(
        patient_id=profile.id,
        doctor_id=doctor.id,
        start_datetime=hold.start_datetime,
        end_datetime=hold.end_datetime,
        status=AppointmentStatus.CONFIRMED,
        reason=payload.reason,
    )
    db.add(appointment)
    db.flush()
    summary = save_symptoms_pending(db, appointment, profile.id, payload.symptoms, now)
    hold.status = SlotHoldStatus.CONVERTED
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict("Slot is no longer available") from exc
    db.refresh(appointment)
    try:
        generate_previsit_summary(db, summary.id, payload.symptoms, now)
    except Exception:
        pass
    try:
        from app.services.notifications import after_appointment_confirmed

        after_appointment_confirmed(db, appointment.id)
    except Exception:
        db.rollback()
    db.refresh(appointment)
    return appointment


def _can_access_appointment(user: User, appointment: Appointment) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.PATIENT and user.patient_profile is not None:
        return appointment.patient_id == user.patient_profile.id
    if user.role == UserRole.DOCTOR and user.doctor_profile is not None:
        return appointment.doctor_id == user.doctor_profile.id
    return False


def get_appointment(db: Session, user: User, appointment_id: int) -> Appointment:
    appointment = db.scalar(
        select(Appointment).where(Appointment.id == appointment_id).options(*APPOINTMENT_LOAD_OPTIONS)
    )
    if appointment is None:
        raise ServiceError(status_code=404, detail="Appointment not found")
    if not _can_access_appointment(user, appointment):
        raise ServiceError(status_code=403, detail="You cannot access this appointment")
    return appointment


def list_appointments(db: Session, user: User) -> list[Appointment]:
    query = select(Appointment).options(*APPOINTMENT_LOAD_OPTIONS).order_by(Appointment.start_datetime)
    if user.role == UserRole.ADMIN:
        pass
    elif user.role == UserRole.PATIENT:
        profile = require_patient_profile(user)
        query = query.where(Appointment.patient_id == profile.id)
    elif user.role == UserRole.DOCTOR:
        profile = require_doctor_profile(user)
        query = query.where(Appointment.doctor_id == profile.id)
    else:
        raise ServiceError(status_code=403, detail="Unauthorized")
    return list(db.scalars(query).all())


def _assert_can_cancel(user: User, appointment: Appointment) -> None:
    if not _can_access_appointment(user, appointment):
        raise ServiceError(status_code=403, detail="You cannot cancel this appointment")


def cancel_appointment(
    db: Session,
    user: User,
    appointment_id: int,
    payload: AppointmentCancel,
    now: datetime,
) -> Appointment:
    appointment = get_appointment(db, user, appointment_id)
    _assert_can_cancel(user, appointment)
    appointment = _lock_appointment(db, appointment.id)
    _assert_can_cancel(user, appointment)
    if appointment.status not in _MUTATING_STATUSES:
        raise _conflict("Only pending or confirmed appointments can be cancelled")
    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancelled_at = now
    appointment.cancellation_reason = payload.reason
    db.commit()
    db.refresh(appointment)
    try:
        from app.services.notifications import after_appointment_cancelled

        after_appointment_cancelled(db, appointment.id)
    except Exception:
        db.rollback()
    db.refresh(appointment)
    return appointment


def reschedule_appointment(
    db: Session,
    patient: User,
    appointment_id: int,
    payload: AppointmentReschedule,
    now: datetime,
) -> Appointment:
    profile = require_patient_profile(patient)
    current = get_appointment(db, patient, appointment_id)
    if current.patient_id != profile.id:
        raise ServiceError(status_code=403, detail="You can only reschedule your own appointment")

    hold = db.get(AppointmentSlotHold, payload.hold_id)
    if hold is None:
        raise ServiceError(status_code=404, detail="Slot hold not found")
    if hold.patient_id != profile.id:
        raise ServiceError(status_code=403, detail="You can only use your own slot hold")
    if hold.doctor_id != current.doctor_id:
        raise _conflict("Reschedule hold must be for the same doctor")

    doctor = _lock_doctor(db, hold.doctor_id)
    current = _lock_appointment(db, appointment_id)
    if current.patient_id != profile.id:
        raise ServiceError(status_code=403, detail="You can only reschedule your own appointment")
    if current.status not in _MUTATING_STATUSES:
        raise _conflict("Only pending or confirmed appointments can be rescheduled")
    if hold.doctor_id != current.doctor_id:
        raise _conflict("Reschedule hold must be for the same doctor")

    ensure_doctor_can_accept_bookings(doctor)
    _expire_stale_holds(db, doctor.id, now)
    db.refresh(hold)
    if _is_hold_expired(hold, now):
        if hold.status == SlotHoldStatus.ACTIVE:
            hold.status = SlotHoldStatus.EXPIRED
            db.commit()
        raise _conflict("Slot hold has expired")
    if hold.status != SlotHoldStatus.ACTIVE:
        raise _conflict("Slot hold is no longer active")
    if not _slot_is_available(
        db,
        doctor.id,
        hold.start_datetime,
        hold.end_datetime,
        now,
        ignore_hold_id=hold.id,
    ):
        raise _conflict("Slot is no longer available")

    # Single transaction: free the old range and occupy the new one. Do not
    # cancel-then-create in separate commits — a failed insert would leave the
    # patient with no appointment.
    current.status = AppointmentStatus.RESCHEDULED
    replacement = Appointment(
        patient_id=profile.id,
        doctor_id=doctor.id,
        start_datetime=hold.start_datetime,
        end_datetime=hold.end_datetime,
        status=AppointmentStatus.CONFIRMED,
        reason=current.reason,
        rescheduled_from_appointment_id=current.id,
    )
    db.add(replacement)
    db.flush()
    original_symptoms = db.scalar(
        select(SymptomSubmission).where(SymptomSubmission.appointment_id == current.id)
    )
    if original_symptoms is not None:
        from app.services.previsit import save_symptoms_pending

        save_symptoms_pending(db, replacement, profile.id, original_symptoms.symptoms, now)
    hold.status = SlotHoldStatus.CONVERTED
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict("Slot is no longer available") from exc
    db.refresh(replacement)
    try:
        from app.services.notifications import after_appointment_rescheduled

        after_appointment_rescheduled(db, current.id, replacement.id)
    except Exception:
        db.rollback()
    db.refresh(replacement)
    return replacement
