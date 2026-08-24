"""Pre-visit symptom storage and Gemini summary generation.

LLM calls happen after the appointment transaction commits.
Failures never roll back a saved booking or the original symptoms.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.integrations.llm import LLMError, get_llm_client
from app.models import AISymptomSummary, Appointment, SymptomSubmission, User
from app.models.enums import AISummaryStatus, UrgencyLevel
from app.schemas.previsit import PrevisitSummaryPublic
from app.services.errors import ServiceError

PREVISIT_PROMPT_TEMPLATE = """Analyse these symptoms and return:
urgency level (Low / Medium / High),
chief complaint,
and three suggested questions for the doctor.

Symptoms:
{symptoms}"""

VALID_URGENCY = {item.value for item in UrgencyLevel}
_URGENCY_BY_LOWER = {item.lower(): item for item in VALID_URGENCY}


@dataclass(frozen=True)
class ParsedPrevisitSummary:
    urgency_level: str
    chief_complaint: str
    suggested_questions: list[str]


def build_previsit_prompt(symptoms: str) -> str:
    return PREVISIT_PROMPT_TEMPLATE.format(symptoms=symptoms.strip())


def _extract_json_object(raw: str) -> dict:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Gemini response must be a JSON object")
    return payload


def _questions_from_value(questions: object) -> list[str]:
    if not isinstance(questions, list):
        raise ValueError("suggested questions must be a list of three strings")
    cleaned = [str(item).strip() for item in questions if str(item).strip()]
    if len(cleaned) != 3:
        raise ValueError("exactly three suggested questions are required")
    return cleaned


def _parse_from_dict(payload: dict) -> ParsedPrevisitSummary:
    urgency = str(payload.get("urgency_level") or payload.get("urgency") or "").strip()
    urgency_normalized = _URGENCY_BY_LOWER.get(urgency.lower())
    if urgency_normalized is None:
        raise ValueError("urgency level must be Low, Medium, or High")
    chief = str(payload.get("chief_complaint") or "").strip()
    if not chief:
        raise ValueError("chief complaint is required")
    return ParsedPrevisitSummary(
        urgency_level=urgency_normalized,
        chief_complaint=chief,
        suggested_questions=_questions_from_value(payload.get("suggested_questions")),
    )


def _parse_from_text(raw: str) -> ParsedPrevisitSummary:
    urgency_match = re.search(
        r"urgency\s*(?:level)?\s*[:\-–]?\s*(Low|Medium|High)",
        raw,
        re.IGNORECASE,
    )
    if not urgency_match:
        raise ValueError("urgency level must be Low, Medium, or High")
    chief_match = re.search(
        r"chief\s*complaint\s*[:\-–]\s*(.+)",
        raw,
        re.IGNORECASE,
    )
    if not chief_match:
        raise ValueError("chief complaint is required")
    chief = chief_match.group(1).strip().splitlines()[0].strip(" .")
    if not chief:
        raise ValueError("chief complaint is required")

    questions: list[str] = []
    parts = re.split(
        r"suggested\s*questions(?:\s+for\s+the\s+doctor)?\s*[:\-–]?",
        raw,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    search_text = parts[1] if len(parts) == 2 else raw
    for match in re.finditer(r"^\s*(?:\d+[.)]|[-*])\s+(.+)$", search_text, re.MULTILINE):
        item = match.group(1).strip()
        if item:
            questions.append(item)
        if len(questions) == 3:
            break
    if len(questions) != 3:
        raise ValueError("exactly three suggested questions are required")
    return ParsedPrevisitSummary(
        urgency_level=_URGENCY_BY_LOWER[urgency_match.group(1).lower()],
        chief_complaint=chief,
        suggested_questions=questions,
    )


def parse_previsit_response(raw: str) -> ParsedPrevisitSummary:
    try:
        payload = _extract_json_object(raw)
    except (json.JSONDecodeError, ValueError):
        return _parse_from_text(raw)
    return _parse_from_dict(payload)


def save_symptoms_pending(
    db: Session,
    appointment: Appointment,
    patient_id: int,
    symptoms: str,
    now: datetime,
) -> AISymptomSummary:
    submission = SymptomSubmission(
        appointment_id=appointment.id,
        patient_id=patient_id,
        symptoms=symptoms.strip(),
        submitted_at=now,
    )
    db.add(submission)
    db.flush()
    summary = AISymptomSummary(
        symptom_submission_id=submission.id,
        status=AISummaryStatus.PENDING,
    )
    db.add(summary)
    db.flush()
    return summary


def generate_previsit_summary(db: Session, summary_id: int, symptoms: str, now: datetime) -> None:
    """Call the LLM and persist success or failure. Never raises to booking code."""
    summary = db.get(AISymptomSummary, summary_id)
    if summary is None:
        return
    raw: str | None = None
    try:
        raw = get_llm_client().generate(build_previsit_prompt(symptoms))
        parsed = parse_previsit_response(raw)
        summary.urgency_level = parsed.urgency_level
        summary.chief_complaint = parsed.chief_complaint
        summary.suggested_questions = parsed.suggested_questions
        summary.raw_response = raw
        summary.status = AISummaryStatus.SUCCEEDED
        summary.error_message = None
        summary.generated_at = now
    except (LLMError, ValueError, Exception) as exc:
        summary.urgency_level = None
        summary.chief_complaint = None
        summary.suggested_questions = None
        summary.raw_response = raw
        summary.status = AISummaryStatus.FAILED
        summary.error_message = str(exc)[:2000] or "AI generation failed"
        summary.generated_at = now
    db.commit()


def retry_previsit_summary(
    db: Session,
    user: User,
    appointment_id: int,
    now: datetime,
) -> PrevisitSummaryPublic:
    submission = _load_submission(db, user, appointment_id)
    generate_previsit_summary(db, submission.ai_summary.id, submission.symptoms, now)
    return get_previsit_summary(db, user, appointment_id)


def get_previsit_summary(db: Session, user: User, appointment_id: int) -> PrevisitSummaryPublic:
    submission = _load_submission(db, user, appointment_id)
    summary = submission.ai_summary
    include_raw = user.is_doctor() or user.is_admin()
    return PrevisitSummaryPublic(
        appointment_id=appointment_id,
        symptoms=submission.symptoms,
        submitted_at=submission.submitted_at,
        urgency_level=summary.urgency_level if summary else None,
        chief_complaint=summary.chief_complaint if summary else None,
        suggested_questions=summary.suggested_questions if summary else None,
        status=summary.status if summary else AISummaryStatus.PENDING,
        error_message=summary.error_message if summary else None,
        generated_at=summary.generated_at if summary else None,
        raw_response=(summary.raw_response if summary and include_raw else None),
    )


def _load_submission(db: Session, user: User, appointment_id: int) -> SymptomSubmission:
    from app.services.appointments import get_appointment

    appointment = get_appointment(db, user, appointment_id)
    submission = db.scalar(
        select(SymptomSubmission)
        .where(SymptomSubmission.appointment_id == appointment.id)
        .options(selectinload(SymptomSubmission.ai_summary))
    )
    if submission is None or submission.ai_summary is None:
        raise ServiceError(status_code=404, detail="No symptoms submitted for this appointment")
    return submission
