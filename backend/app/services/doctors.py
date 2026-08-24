"""Admin doctor management: profiles, working hours, leave, and booking eligibility."""

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.security import hash_password
from app.models import (
    Appointment,
    AppointmentSlotHold,
    DoctorLeave,
    DoctorProfile,
    DoctorWorkingHours,
    NotificationLog,
    PatientProfile,
    User,
)
from app.models.enums import (
    AppointmentStatus,
    DoctorLeaveStatus,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    SlotHoldStatus,
    UserRole,
)
from app.schemas.doctor import DoctorCreate, DoctorLeaveIn, DoctorUpdate, WorkingHoursIn
from app.services.auth import get_user_by_email, normalize_email
from app.services.errors import ServiceError

DOCTOR_LOAD_OPTIONS = (
    selectinload(DoctorProfile.user),
    selectinload(DoctorProfile.working_hours),
    selectinload(DoctorProfile.leaves),
)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def working_hours_overlap(hours: list[WorkingHoursIn]) -> bool:
    by_day: dict[int, list[tuple[time, time]]] = {}
    for item in hours:
        by_day.setdefault(item.day_of_week, []).append((item.start_time, item.end_time))
    for shifts in by_day.values():
        ordered = sorted(shifts, key=lambda shift: shift[0])
        for index in range(1, len(ordered)):
            previous_end = ordered[index - 1][1]
            current_start = ordered[index][0]
            if current_start < previous_end:
                return True
    return False


def ensure_no_working_hour_overlap(hours: list[WorkingHoursIn]) -> None:
    if working_hours_overlap(hours):
        raise ServiceError(
            status_code=409,
            detail="Working hours overlap on the same weekday",
        )


def ensure_doctor_can_accept_bookings(doctor: DoctorProfile) -> None:
    user = doctor.user
    if not doctor.is_active or user is None or not user.is_active:
        raise ServiceError(
            status_code=409,
            detail="Inactive doctors cannot accept new bookings",
        )


def get_doctor_or_404(db: Session, doctor_id: int) -> DoctorProfile:
    doctor = db.scalar(
        select(DoctorProfile).where(DoctorProfile.id == doctor_id).options(*DOCTOR_LOAD_OPTIONS)
    )
    if doctor is None:
        raise ServiceError(status_code=404, detail="Doctor not found")
    return doctor


def list_doctors(db: Session) -> list[DoctorProfile]:
    return list(
        db.scalars(
            select(DoctorProfile).options(*DOCTOR_LOAD_OPTIONS).order_by(DoctorProfile.id)
        ).all()
    )


def list_catalog_doctors(db: Session, specialization: str | None = None) -> list[DoctorProfile]:
    doctors = [
        doctor
        for doctor in list_doctors(db)
        if doctor.is_active and doctor.user is not None and doctor.user.is_active
    ]
    if specialization and specialization.strip():
        needle = specialization.strip().lower()
        doctors = [doctor for doctor in doctors if needle in doctor.specialization.lower()]
    return doctors


def _add_working_hours(doctor: DoctorProfile, hours: list[WorkingHoursIn]) -> None:
    ensure_no_working_hour_overlap(hours)
    for item in hours:
        doctor.working_hours.append(
            DoctorWorkingHours(
                day_of_week=item.day_of_week,
                start_time=item.start_time,
                end_time=item.end_time,
            )
        )


def create_doctor(db: Session, payload: DoctorCreate) -> DoctorProfile:
    email = normalize_email(payload.email)
    if get_user_by_email(db, email) is not None:
        raise ServiceError(status_code=409, detail="Email already registered")
    ensure_no_working_hour_overlap(payload.working_hours)

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    db.flush()
    doctor = DoctorProfile(
        user_id=user.id,
        specialization=payload.specialization.strip(),
        qualification=_blank_to_none(payload.qualification),
        bio=_blank_to_none(payload.bio),
        slot_duration_minutes=payload.slot_duration_minutes,
        is_active=payload.is_active,
    )
    db.add(doctor)
    db.flush()
    _add_working_hours(doctor, payload.working_hours)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError(status_code=409, detail="Could not create doctor") from exc
    return get_doctor_or_404(db, doctor.id)


def update_doctor(db: Session, doctor_id: int, payload: DoctorUpdate) -> DoctorProfile:
    doctor = get_doctor_or_404(db, doctor_id)
    data = payload.model_dump(exclude_unset=True)
    if "full_name" in data and data["full_name"] is not None:
        doctor.user.full_name = data["full_name"].strip()
    if "specialization" in data and data["specialization"] is not None:
        doctor.specialization = data["specialization"].strip()
    if "qualification" in data:
        doctor.qualification = _blank_to_none(data["qualification"])
    if "bio" in data:
        doctor.bio = _blank_to_none(data["bio"])
    if "slot_duration_minutes" in data and data["slot_duration_minutes"] is not None:
        doctor.slot_duration_minutes = data["slot_duration_minutes"]
    if "is_active" in data and data["is_active"] is not None:
        doctor.is_active = data["is_active"]
    db.commit()
    return get_doctor_or_404(db, doctor_id)


def set_doctor_active(db: Session, doctor_id: int, is_active: bool) -> DoctorProfile:
    doctor = get_doctor_or_404(db, doctor_id)
    doctor.is_active = is_active
    db.commit()
    return get_doctor_or_404(db, doctor_id)


def replace_working_hours(
    db: Session,
    doctor_id: int,
    hours: list[WorkingHoursIn],
) -> DoctorProfile:
    doctor = get_doctor_or_404(db, doctor_id)
    ensure_no_working_hour_overlap(hours)
    doctor.working_hours.clear()
    db.flush()
    _add_working_hours(doctor, hours)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError(
            status_code=409,
            detail="Working hours overlap on the same weekday",
        ) from exc
    return get_doctor_or_404(db, doctor_id)


def _leave_window(start_date, end_date) -> tuple[datetime, datetime]:
    window_start = datetime.combine(start_date, time.min, tzinfo=UTC)
    window_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    return window_start, window_end


def _patient_leave_cancellation_reason(leave_reason: str | None) -> str:
    base = "Your appointment was cancelled because the doctor is on leave."
    if leave_reason:
        return f"{base} Reason: {leave_reason}"
    return base


def create_doctor_leave(
    db: Session,
    doctor_id: int,
    payload: DoctorLeaveIn,
    admin_id: int,
    now: datetime,
) -> tuple[DoctorLeave, list[int]]:
    doctor = db.scalar(
        select(DoctorProfile)
        .where(DoctorProfile.id == doctor_id)
        .options(*DOCTOR_LOAD_OPTIONS)
        .with_for_update()
    )
    if doctor is None:
        raise ServiceError(status_code=404, detail="Doctor not found")

    leave_reason = _blank_to_none(payload.reason)
    leave = DoctorLeave(
        doctor_id=doctor.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=leave_reason,
        status=DoctorLeaveStatus.SCHEDULED,
        created_by_admin_id=admin_id,
    )
    db.add(leave)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError(
            status_code=409,
            detail="Leave overlaps an existing leave period for this doctor",
        ) from exc

    window_start, window_end = _leave_window(payload.start_date, payload.end_date)
    affected = list(
        db.scalars(
            select(Appointment)
            .where(
                Appointment.doctor_id == doctor.id,
                Appointment.status.in_(
                    [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]
                ),
                Appointment.start_datetime < window_end,
                Appointment.end_datetime > window_start,
            )
            .options(selectinload(Appointment.patient).selectinload(PatientProfile.user))
            .with_for_update()
        ).all()
    )

    cancellation_reason = _patient_leave_cancellation_reason(leave_reason)
    cancelled_ids: list[int] = []
    for appointment in affected:
        appointment.status = AppointmentStatus.CANCELLED_LEAVE
        appointment.cancelled_at = now
        appointment.cancellation_reason = cancellation_reason
        cancelled_ids.append(appointment.id)
        patient_user = appointment.patient.user
        db.add(
            NotificationLog(
                user_id=patient_user.id,
                appointment_id=appointment.id,
                notification_type=NotificationType.DOCTOR_LEAVE_CANCELLATION,
                channel=NotificationChannel.EMAIL,
                recipient=patient_user.email,
                subject="CareConnect appointment cancelled — doctor leave",
                status=NotificationStatus.PENDING,
                idempotency_key=f"leave:{leave.id}:appointment:{appointment.id}:patient:{patient_user.id}",
            )
        )

    db.execute(
        update(AppointmentSlotHold)
        .where(
            AppointmentSlotHold.doctor_id == doctor.id,
            AppointmentSlotHold.status == SlotHoldStatus.ACTIVE,
            AppointmentSlotHold.start_datetime < window_end,
            AppointmentSlotHold.end_datetime > window_start,
        )
        .values(status=SlotHoldStatus.RELEASED)
    )

    db.add(
        NotificationLog(
            user_id=doctor.user_id,
            appointment_id=None,
            notification_type=NotificationType.DOCTOR_LEAVE_PROCESSED,
            channel=NotificationChannel.EMAIL,
            recipient=doctor.user.email,
            subject="CareConnect leave recorded",
            status=NotificationStatus.PENDING,
            idempotency_key=f"leave:{leave.id}:doctor:{doctor.user_id}",
        )
    )
    leave.status = DoctorLeaveStatus.PROCESSED
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ServiceError(
            status_code=409,
            detail="Leave could not be saved because of a booking conflict",
        ) from exc
    db.refresh(leave)
    try:
        from app.services.calendar_sync import enqueue_calendar_deletes
        from app.services.notifications import queue_leave_notification_sends

        queue_leave_notification_sends()
        enqueue_calendar_deletes(db, cancelled_ids)
    except Exception:
        pass
    return leave, cancelled_ids
