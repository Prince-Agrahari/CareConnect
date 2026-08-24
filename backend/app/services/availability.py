"""Backend slot generation. Frontend availability is never trusted."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentSlotHold, DoctorLeave
from app.models.enums import APPOINTMENT_BLOCKING_STATUSES, DoctorLeaveStatus, SlotHoldStatus
from app.schemas.availability import AvailabilityResponse, SlotPublic
from app.services.doctors import get_doctor_or_404


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _ranges_overlap(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    return start_a < end_b and start_b < end_a


def _doctor_is_on_leave(db: Session, doctor_id: int, target_date: date) -> bool:
    leave = db.scalar(
        select(DoctorLeave.id).where(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.start_date <= target_date,
            DoctorLeave.end_date >= target_date,
            DoctorLeave.status != DoctorLeaveStatus.CANCELLED,
        )
    )
    return leave is not None


def _occupied_ranges(
    db: Session,
    doctor_id: int,
    day_start: datetime,
    day_end: datetime,
    now: datetime,
    ignore_hold_id: int | None = None,
) -> list[tuple[datetime, datetime]]:
    blocking_statuses = [status.value for status in APPOINTMENT_BLOCKING_STATUSES]
    appointments = db.scalars(
        select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(blocking_statuses),
            Appointment.start_datetime < day_end,
            Appointment.end_datetime > day_start,
        )
    ).all()
    hold_query = select(AppointmentSlotHold).where(
        AppointmentSlotHold.doctor_id == doctor_id,
        AppointmentSlotHold.status == SlotHoldStatus.ACTIVE,
        AppointmentSlotHold.expires_at > now,
        AppointmentSlotHold.start_datetime < day_end,
        AppointmentSlotHold.end_datetime > day_start,
    )
    if ignore_hold_id is not None:
        hold_query = hold_query.where(AppointmentSlotHold.id != ignore_hold_id)
    holds = db.scalars(hold_query).all()
    return [(row.start_datetime, row.end_datetime) for row in appointments] + [
        (row.start_datetime, row.end_datetime) for row in holds
    ]


def _generate_window_slots(
    *,
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    now: datetime,
    occupied: list[tuple[datetime, datetime]],
) -> list[SlotPublic]:
    slots: list[SlotPublic] = []
    cursor = window_start
    while cursor + duration <= window_end:
        slot_end = cursor + duration
        is_future = cursor > now
        is_free = not any(
            _ranges_overlap(cursor, slot_end, busy_start, busy_end)
            for busy_start, busy_end in occupied
        )
        if is_future and is_free:
            slots.append(SlotPublic(start_datetime=cursor, end_datetime=slot_end))
        cursor = slot_end
    return slots


def get_doctor_availability(
    db: Session,
    doctor_id: int,
    target_date: date,
    now: datetime,
    ignore_hold_id: int | None = None,
) -> AvailabilityResponse:
    doctor = get_doctor_or_404(db, doctor_id)
    now = _as_utc(now)
    response = AvailabilityResponse(
        doctor_id=doctor.id,
        date=target_date,
        slot_duration_minutes=doctor.slot_duration_minutes,
        is_active=doctor.is_active and doctor.user.is_active,
        slots=[],
    )
    if not response.is_active:
        return response
    if target_date < now.date():
        return response
    if _doctor_is_on_leave(db, doctor.id, target_date):
        return response

    duration = timedelta(minutes=doctor.slot_duration_minutes)
    if duration <= timedelta(0):
        return response

    weekday = target_date.weekday()
    windows = [hours for hours in doctor.working_hours if hours.day_of_week == weekday]
    if not windows:
        return response

    day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    occupied = _occupied_ranges(
        db,
        doctor.id,
        day_start,
        day_end,
        now,
        ignore_hold_id=ignore_hold_id,
    )

    slots: list[SlotPublic] = []
    for window in sorted(windows, key=lambda item: item.start_time):
        slots.extend(
            _generate_window_slots(
                window_start=datetime.combine(target_date, window.start_time, tzinfo=UTC),
                window_end=datetime.combine(target_date, window.end_time, tzinfo=UTC),
                duration=duration,
                now=now,
                occupied=occupied,
            )
        )
    response.slots = slots
    return response
