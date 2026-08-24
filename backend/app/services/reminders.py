"""Medication reminder schedules from explicit prescription frequency only."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Appointment, MedicationReminder, Prescription, PrescriptionMedication
from app.models.enums import AppointmentStatus, MedicationReminderStatus, NotificationType
from app.models.user import PatientProfile
from app.services.notifications import get_or_create_notification

_TIME = r"(\d{1,2}:\d{2})"


def parse_clock_time(value: str) -> time | None:
    try:
        hours_text, minutes_text = value.split(":", 1)
        hours = int(hours_text)
        minutes = int(minutes_text)
    except (TypeError, ValueError):
        return None
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        return None
    return time(hours, minutes)


def parse_frequency_times(frequency: str) -> list[time] | None:
    """Return reminder times only when the frequency states them explicitly."""
    text = " ".join(frequency.strip().lower().split())
    once = re.fullmatch(rf"(?:once(?: a day| daily)?|daily|every day) at {_TIME}", text)
    if once:
        parsed = parse_clock_time(once.group(1))
        return [parsed] if parsed else None
    twice = re.fullmatch(rf"twice(?: a day| daily) at {_TIME} and {_TIME}", text)
    if twice:
        first = parse_clock_time(twice.group(1))
        second = parse_clock_time(twice.group(2))
        if first is None or second is None or first == second:
            return None
        return sorted([first, second])
    three = re.fullmatch(
        rf"(?:three times(?: a day| daily)|thrice daily) at {_TIME}, {_TIME}(?: and|, and) {_TIME}",
        text,
    )
    if three:
        times = [parse_clock_time(three.group(i)) for i in (1, 2, 3)]
        if any(item is None for item in times) or len(set(times)) != 3:
            return None
        return sorted(times)  # type: ignore[arg-type]
    return None


def parse_duration_days(duration: str) -> int | None:
    text = " ".join(duration.strip().lower().split())
    days = re.fullmatch(r"(\d+) days?", text)
    if days:
        count = int(days.group(1))
        return count if count > 0 else None
    weeks = re.fullmatch(r"(\d+) weeks?", text)
    if weeks:
        count = int(weeks.group(1))
        return count * 7 if count > 0 else None
    return None


def _combine(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=UTC)


def _first_due(now: datetime, clock: time, start: date, end: date) -> datetime | None:
    candidate_day = max(now.date(), start)
    due = _combine(candidate_day, clock)
    if due < now:
        due = _combine(candidate_day + timedelta(days=1), clock)
    if due.date() > end:
        return None
    return due


def create_reminders_for_prescription(
    db: Session,
    prescription: Prescription,
    patient_id: int,
    now: datetime,
) -> list[MedicationReminder]:
    medications = list(
        db.scalars(
            select(PrescriptionMedication).where(
                PrescriptionMedication.prescription_id == prescription.id
            )
        )
    )
    created: list[MedicationReminder] = []
    for medication in medications:
        times = parse_frequency_times(medication.frequency)
        days = parse_duration_days(medication.duration)
        if not times or not days:
            continue
        start = now.date()
        end = start + timedelta(days=days - 1)
        existing_times = {
            row.remind_at
            for row in db.scalars(
                select(MedicationReminder).where(
                    MedicationReminder.prescription_medication_id == medication.id
                )
            )
        }
        for clock in times:
            if clock in existing_times:
                continue
            next_due = _first_due(now, clock, start, end)
            reminder = MedicationReminder(
                prescription_medication_id=medication.id,
                patient_id=patient_id,
                remind_at=clock,
                start_date=start,
                end_date=end,
                next_scheduled_at=next_due,
                status=(
                    MedicationReminderStatus.ACTIVE
                    if next_due is not None
                    else MedicationReminderStatus.COMPLETED
                ),
            )
            db.add(reminder)
            created.append(reminder)
    db.flush()
    return created


def dispatch_due_medication_reminders(db: Session, now: datetime) -> list[int]:
    due = list(
        db.scalars(
            select(MedicationReminder)
            .where(
                MedicationReminder.status == MedicationReminderStatus.ACTIVE,
                MedicationReminder.next_scheduled_at.is_not(None),
                MedicationReminder.next_scheduled_at <= now,
            )
            .options(
                selectinload(MedicationReminder.medication),
                selectinload(MedicationReminder.patient).selectinload(PatientProfile.user),
            )
            .with_for_update()
        )
    )
    notification_ids: list[int] = []
    for reminder in due:
        if reminder.next_scheduled_at is None:
            continue
        patient_user = reminder.patient.user
        medicine = reminder.medication.medicine_name
        slot = reminder.next_scheduled_at
        key = (
            f"medication-reminder:{reminder.id}:"
            f"{slot.date().isoformat()}:{reminder.remind_at.strftime('%H:%M')}"
        )
        row, _created = get_or_create_notification(
            db,
            user_id=patient_user.id,
            appointment_id=None,
            notification_type=NotificationType.MEDICATION_REMINDER,
            recipient=patient_user.email,
            subject=f"CareConnect medication reminder: {medicine}",
            idempotency_key=key,
        )
        notification_ids.append(row.id)
        nxt = slot + timedelta(days=1)
        if nxt.date() > reminder.end_date:
            reminder.next_scheduled_at = None
            reminder.status = MedicationReminderStatus.COMPLETED
        else:
            reminder.next_scheduled_at = nxt
        reminder.last_sent_at = now
    db.commit()
    return notification_ids


def list_patient_medication_reminders(db: Session, patient_id: int):
    return list(
        db.scalars(
            select(MedicationReminder)
            .where(MedicationReminder.patient_id == patient_id)
            .options(selectinload(MedicationReminder.medication))
            .order_by(MedicationReminder.start_date, MedicationReminder.remind_at)
        ).all()
    )


def dispatch_due_appointment_reminders(db: Session, now: datetime) -> list[int]:
    from app.core.config import settings
    from app.services.notifications import record_appointment_reminder

    window_end = now + timedelta(hours=settings.APPOINTMENT_REMINDER_HOURS)
    appointments = list(
        db.scalars(
            select(Appointment).where(
                Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]),
                Appointment.start_datetime > now,
                Appointment.start_datetime <= window_end,
            )
        )
    )
    notification_ids: list[int] = []
    for appointment in appointments:
        row, _created = record_appointment_reminder(db, appointment.id)
        notification_ids.append(row.id)
    db.commit()
    return notification_ids
