"""Doctor visit notes, prescriptions, and post-visit Gemini summaries.

LLM calls happen after clinical notes and prescriptions commit.
Failures never roll back saved notes or medications.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.integrations.llm import LLMError, get_llm_client
from app.models import (
    Appointment,
    Prescription,
    PrescriptionMedication,
    SymptomSubmission,
    User,
    VisitNote,
)
from app.models.doctor import DoctorProfile
from app.models.enums import AISummaryStatus, AppointmentStatus
from app.models.user import PatientProfile
from app.schemas.appointment import AppointmentPublic
from app.schemas.visit import MedicationCreate, MedicationPublic, VisitPublic, VisitSubmit
from app.services.appointments import get_appointment, require_doctor_profile
from app.services.errors import ServiceError

VISIT_SUMMARY_PROMPT_TEMPLATE = """Convert these clinical notes into a patient-friendly summary with medication schedule and follow-up steps:

{notes}"""

AI_GENERATED_LABEL = "[AI-generated]"
AI_DISCLAIMER = "This summary is assistive only and is not a medical diagnosis."


def build_visit_notes_block(
    clinical_notes: str,
    medications: list[MedicationCreate] | list[PrescriptionMedication],
    follow_up_instructions: str | None,
) -> str:
    parts = [clinical_notes.strip()]
    if medications:
        parts.append("Prescribed medication:")
        for med in medications:
            line = (
                f"- {med.medicine_name}: dosage {med.dosage}; "
                f"frequency {med.frequency}; duration {med.duration}"
            )
            instructions = getattr(med, "instructions", None)
            if instructions:
                line += f"; instructions {instructions}"
            parts.append(line)
    else:
        parts.append("Prescribed medication: none")
    follow_up = (follow_up_instructions or "").strip()
    if follow_up:
        parts.append("Follow-up instructions:")
        parts.append(follow_up)
    else:
        parts.append("Follow-up instructions: none")
    return "\n".join(parts)


def build_visit_summary_prompt(
    clinical_notes: str,
    medications: list[MedicationCreate] | list[PrescriptionMedication],
    follow_up_instructions: str | None,
) -> str:
    return VISIT_SUMMARY_PROMPT_TEMPLATE.format(
        notes=build_visit_notes_block(clinical_notes, medications, follow_up_instructions)
    )


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    fenced = re.search(r"```(?:\w+)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text


def label_visit_summary(text: str) -> str:
    body = text.strip()
    if AI_GENERATED_LABEL.lower() not in body.lower():
        body = f"{AI_GENERATED_LABEL} {AI_DISCLAIMER}\n\n{body}"
    elif AI_DISCLAIMER.lower() not in body.lower():
        body = f"{body}\n\n{AI_DISCLAIMER}"
    return body


def validate_visit_summary(
    raw: str,
    medications: list[MedicationCreate] | list[PrescriptionMedication],
    follow_up_instructions: str | None,
) -> str:
    text = _strip_fences(raw)
    if not text:
        raise ValueError("patient-friendly summary is empty")
    lowered = text.lower()
    for med in medications:
        if med.medicine_name.lower() not in lowered:
            raise ValueError(
                f"summary is missing prescribed medication: {med.medicine_name}"
            )
    follow_up = (follow_up_instructions or "").strip()
    if follow_up and "follow" not in lowered:
        raise ValueError("summary must include follow-up instructions")
    return label_visit_summary(text)


def _require_assigned_doctor(user: User, appointment: Appointment):
    profile = require_doctor_profile(user)
    if profile.id != appointment.doctor_id:
        raise ServiceError(
            status_code=403,
            detail="Only the assigned doctor can submit visit notes",
        )
    return profile


def _load_visit_appointment(db: Session, user: User, appointment_id: int) -> Appointment:
    appointment = get_appointment(db, user, appointment_id)
    loaded = db.scalar(
        select(Appointment)
        .where(Appointment.id == appointment.id)
        .options(
            selectinload(Appointment.symptom_submission).selectinload(
                SymptomSubmission.ai_summary
            ),
            selectinload(Appointment.visit_note),
            selectinload(Appointment.prescription).selectinload(Prescription.medications),
            selectinload(Appointment.patient).selectinload(PatientProfile.user),
            selectinload(Appointment.doctor).selectinload(DoctorProfile.user),
        )
    )
    assert loaded is not None
    return loaded


def submit_visit(
    db: Session,
    user: User,
    appointment_id: int,
    payload: VisitSubmit,
    now: datetime,
) -> VisitPublic:
    appointment = _load_visit_appointment(db, user, appointment_id)
    doctor = _require_assigned_doctor(user, appointment)
    if appointment.status not in {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}:
        raise ServiceError(
            status_code=409,
            detail="Visit notes can only be submitted for pending or confirmed appointments",
        )
    existing = db.scalar(select(VisitNote).where(VisitNote.appointment_id == appointment.id))
    if existing is not None:
        raise ServiceError(status_code=409, detail="Visit notes already submitted")

    note = VisitNote(
        appointment_id=appointment.id,
        doctor_id=doctor.id,
        clinical_notes=payload.clinical_notes,
        follow_up_instructions=payload.follow_up_instructions,
        summary_status=AISummaryStatus.PENDING,
    )
    db.add(note)
    if payload.medications:
        prescription = Prescription(
            appointment_id=appointment.id,
            doctor_id=doctor.id,
            patient_id=appointment.patient_id,
        )
        db.add(prescription)
        db.flush()
        for med in payload.medications:
            db.add(
                PrescriptionMedication(
                    prescription_id=prescription.id,
                    medicine_name=med.medicine_name,
                    dosage=med.dosage,
                    frequency=med.frequency,
                    duration=med.duration,
                    instructions=med.instructions,
                )
            )
        db.flush()
        from app.services.reminders import create_reminders_for_prescription

        create_reminders_for_prescription(db, prescription, appointment.patient_id, now)
    appointment.status = AppointmentStatus.COMPLETED
    db.commit()
    db.refresh(note)
    try:
        generate_visit_summary(db, note.id, now)
    except Exception:
        pass
    return get_visit(db, user, appointment_id)


def generate_visit_summary(db: Session, visit_note_id: int, now: datetime) -> None:
    """Call the LLM and persist success or failure. Never raises to visit submit."""
    note = db.scalar(
        select(VisitNote)
        .where(VisitNote.id == visit_note_id)
        .options(
            selectinload(VisitNote.appointment).selectinload(Appointment.prescription).selectinload(
                Prescription.medications
            )
        )
    )
    if note is None:
        return
    medications = []
    if note.appointment is not None and note.appointment.prescription is not None:
        medications = list(note.appointment.prescription.medications)
    raw: str | None = None
    try:
        raw = get_llm_client().generate(
            build_visit_summary_prompt(
                note.clinical_notes,
                medications,
                note.follow_up_instructions,
            )
        )
        summary = validate_visit_summary(raw, medications, note.follow_up_instructions)
        note.patient_friendly_summary = summary
        note.summary_raw_response = raw
        note.summary_status = AISummaryStatus.SUCCEEDED
        note.summary_error = None
        note.summary_generated_at = now
    except (LLMError, ValueError, Exception) as exc:
        note.patient_friendly_summary = None
        note.summary_raw_response = raw
        note.summary_status = AISummaryStatus.FAILED
        note.summary_error = str(exc)[:2000] or "AI generation failed"
        note.summary_generated_at = now
    db.commit()


def retry_visit_summary(
    db: Session,
    user: User,
    appointment_id: int,
    now: datetime,
) -> VisitPublic:
    appointment = _load_visit_appointment(db, user, appointment_id)
    _require_assigned_doctor(user, appointment)
    if appointment.visit_note is None:
        raise ServiceError(status_code=404, detail="No visit notes found for this appointment")
    generate_visit_summary(db, appointment.visit_note.id, now)
    return get_visit(db, user, appointment_id)


def get_visit(db: Session, user: User, appointment_id: int) -> VisitPublic:
    appointment = _load_visit_appointment(db, user, appointment_id)
    submission = appointment.symptom_submission
    summary = submission.ai_summary if submission is not None else None
    note = appointment.visit_note
    prescription = appointment.prescription
    include_clinical = user.is_doctor() or user.is_admin()
    include_raw = include_clinical
    medications = list(prescription.medications) if prescription is not None else []
    return VisitPublic(
        appointment=AppointmentPublic.model_validate(appointment),
        symptoms=submission.symptoms if submission is not None else None,
        urgency_level=summary.urgency_level if summary is not None else None,
        chief_complaint=summary.chief_complaint if summary is not None else None,
        suggested_questions=summary.suggested_questions if summary is not None else None,
        previsit_status=summary.status if summary is not None else None,
        clinical_notes=note.clinical_notes if note is not None and include_clinical else None,
        follow_up_instructions=note.follow_up_instructions if note is not None else None,
        medications=[MedicationPublic.model_validate(item) for item in medications],
        patient_friendly_summary=note.patient_friendly_summary if note is not None else None,
        summary_status=note.summary_status if note is not None else None,
        summary_error=note.summary_error if note is not None else None,
        summary_generated_at=note.summary_generated_at if note is not None else None,
        summary_raw_response=(
            note.summary_raw_response if note is not None and include_raw else None
        ),
        is_ai_generated=bool(
            note is not None and note.summary_status == AISummaryStatus.SUCCEEDED
        ),
    )
