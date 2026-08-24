"""Doctor visit notes, prescriptions, and post-visit Gemini summary tests."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.session import SessionLocal
from app.integrations.llm import LLMError, set_llm_client
from app.main import app
from app.models.enums import UserRole
from app.services.auth import create_user_with_role
from app.services.visit import build_visit_summary_prompt, validate_visit_summary
from app.schemas.visit import MedicationCreate

client = TestClient(app)

MONDAY_START = "2026-09-07T09:00:00+00:00"
MONDAY_END = "2026-09-07T09:30:00+00:00"
SLOT = {"start_datetime": MONDAY_START, "end_datetime": MONDAY_END}
SYMPTOMS = "Headache for three days, worse in the morning, with some nausea."
PREVISIT_PAYLOAD = {
    "urgency_level": "Medium",
    "chief_complaint": "Persistent morning headache with nausea",
    "suggested_questions": [
        "When did the headache start?",
        "Have you taken any medication?",
        "Any vision changes or vomiting?",
    ],
}
CLINICAL_NOTES = "Tension-type headache. Advised rest and hydration."
FOLLOW_UP = "Return in 2 weeks if symptoms persist."
MEDICATION = {
    "medicine_name": "Ibuprofen",
    "dosage": "400 mg",
    "frequency": "twice daily",
    "duration": "5 days",
    "instructions": "Take after food",
}
VISIT_SUMMARY = (
    "You were seen for a tension headache. Take Ibuprofen 400 mg twice daily "
    "for 5 days after food. Follow-up: Return in 2 weeks if symptoms persist."
)
VISIT_BODY = {
    "clinical_notes": CLINICAL_NOTES,
    "follow_up_instructions": FOLLOW_UP,
    "medications": [MEDICATION],
}


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.com"


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_overrides() -> None:
    yield
    set_llm_client(None)
    app.dependency_overrides.clear()


def _freeze(moment: datetime) -> None:
    app.dependency_overrides[utc_now] = lambda: moment


@pytest.fixture()
def before_monday_hours() -> datetime:
    moment = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    _freeze(moment)
    return moment


@pytest.fixture()
def admin_token(db: Session) -> str:
    email = _email("admin")
    create_user_with_role(
        db,
        email=email,
        password="securepass1",
        full_name="Admin User",
        role=UserRole.ADMIN,
    )
    response = client.post("/api/auth/login", json={"email": email, "password": "securepass1"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _register_patient() -> str:
    email = _email("patient")
    register = client.post(
        "/api/auth/register",
        json={"email": email, "password": "securepass1", "full_name": "Visit Patient"},
    )
    assert register.status_code == 201
    login = client.post("/api/auth/login", json={"email": email, "password": "securepass1"})
    return login.json()["access_token"]


def _create_doctor(admin_token: str) -> dict:
    response = client.post(
        "/api/admin/doctors",
        json={
            "email": _email("doctor"),
            "password": "securepass1",
            "full_name": "Dr Visit",
            "specialization": "General Medicine",
            "slot_duration_minutes": 30,
            "working_hours": [{"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00"}],
        },
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 201
    return response.json()


def _doctor_token(doctor: dict) -> str:
    login = client.post(
        "/api/auth/login",
        json={"email": doctor["email"], "password": "securepass1"},
    )
    assert login.status_code == 200
    return login.json()["access_token"]


def _book(patient_token: str, doctor_id: int) -> dict:
    hold = client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor_id, **SLOT},
        headers=_auth_header(patient_token),
    )
    assert hold.status_code == 201, hold.text
    confirmed = client.post(
        "/api/appointments/confirm",
        json={"hold_id": hold.json()["id"], "reason": "Checkup", "symptoms": SYMPTOMS},
        headers=_auth_header(patient_token),
    )
    assert confirmed.status_code == 201, confirmed.text
    return confirmed.json()


class _RecordingLLM:
    def __init__(self, visit_text: str = VISIT_SUMMARY) -> None:
        self.visit_text = visit_text
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if prompt.startswith("Analyse these symptoms"):
            return json.dumps(PREVISIT_PAYLOAD)
        return self.visit_text


class _FailingVisitLLM(_RecordingLLM):
    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if prompt.startswith("Analyse these symptoms"):
            return json.dumps(PREVISIT_PAYLOAD)
        raise LLMError("Gemini unavailable")


def test_validate_visit_summary_preserves_medication_and_labels() -> None:
    meds = [MedicationCreate.model_validate(MEDICATION)]
    labeled = validate_visit_summary(VISIT_SUMMARY, meds, FOLLOW_UP)
    assert labeled.startswith("[AI-generated]")
    assert "not a medical diagnosis" in labeled
    assert "Ibuprofen" in labeled
    assert "Follow-up" in labeled


def test_validate_visit_summary_rejects_invented_or_dropped_medication() -> None:
    meds = [MedicationCreate.model_validate(MEDICATION)]
    with pytest.raises(ValueError, match="Ibuprofen"):
        validate_visit_summary("Rest and drink water. Follow-up in two weeks.", meds, FOLLOW_UP)


def test_doctor_can_view_appointment_symptoms_and_previsit_summary(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    set_llm_client(_RecordingLLM())
    doctor = _create_doctor(admin_token)
    patient_token = _register_patient()
    appointment = _book(patient_token, doctor["id"])
    doctor_token = _doctor_token(doctor)

    visit = client.get(
        f"/api/appointments/{appointment['id']}/visit",
        headers=_auth_header(doctor_token),
    )
    assert visit.status_code == 200, visit.text
    body = visit.json()
    assert body["appointment"]["id"] == appointment["id"]
    assert body["appointment"]["status"] == "confirmed"
    assert body["symptoms"] == SYMPTOMS
    assert body["urgency_level"] == "Medium"
    assert body["chief_complaint"] == PREVISIT_PAYLOAD["chief_complaint"]
    assert body["suggested_questions"] == PREVISIT_PAYLOAD["suggested_questions"]
    assert body["previsit_status"] == "succeeded"
    assert body["clinical_notes"] is None
    assert body["patient_friendly_summary"] is None


def test_assigned_doctor_can_submit_visit_and_store_ai_summary(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    llm = _RecordingLLM()
    set_llm_client(llm)
    doctor = _create_doctor(admin_token)
    patient_token = _register_patient()
    appointment = _book(patient_token, doctor["id"])
    doctor_token = _doctor_token(doctor)

    created = client.post(
        f"/api/appointments/{appointment['id']}/visit",
        json=VISIT_BODY,
        headers=_auth_header(doctor_token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["appointment"]["status"] == "completed"
    assert body["clinical_notes"] == CLINICAL_NOTES
    assert body["follow_up_instructions"] == FOLLOW_UP
    assert body["medications"][0]["medicine_name"] == "Ibuprofen"
    assert body["medications"][0]["dosage"] == "400 mg"
    assert body["medications"][0]["frequency"] == "twice daily"
    assert body["medications"][0]["duration"] == "5 days"
    assert body["medications"][0]["instructions"] == "Take after food"
    assert body["summary_status"] == "succeeded"
    assert body["is_ai_generated"] is True
    assert body["patient_friendly_summary"].startswith("[AI-generated]")
    assert "Ibuprofen" in body["patient_friendly_summary"]
    assert "Follow-up" in body["patient_friendly_summary"]
    assert body["summary_error"] is None
    expected_prompt = build_visit_summary_prompt(
        CLINICAL_NOTES,
        [MedicationCreate.model_validate(MEDICATION)],
        FOLLOW_UP,
    )
    assert expected_prompt in llm.prompts
    assert expected_prompt.startswith(
        "Convert these clinical notes into a patient-friendly summary with medication schedule and follow-up steps:"
    )

    patient_view = client.get(
        f"/api/appointments/{appointment['id']}/visit",
        headers=_auth_header(patient_token),
    )
    assert patient_view.status_code == 200
    patient_body = patient_view.json()
    assert patient_body["clinical_notes"] is None
    assert patient_body["patient_friendly_summary"].startswith("[AI-generated]")
    assert patient_body["medications"][0]["medicine_name"] == "Ibuprofen"
    assert patient_body["summary_raw_response"] is None


def test_failed_gemini_still_saves_notes_and_prescription(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    set_llm_client(_FailingVisitLLM())
    doctor = _create_doctor(admin_token)
    patient_token = _register_patient()
    appointment = _book(patient_token, doctor["id"])
    doctor_token = _doctor_token(doctor)

    created = client.post(
        f"/api/appointments/{appointment['id']}/visit",
        json=VISIT_BODY,
        headers=_auth_header(doctor_token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["appointment"]["status"] == "completed"
    assert body["clinical_notes"] == CLINICAL_NOTES
    assert body["medications"][0]["medicine_name"] == "Ibuprofen"
    assert body["summary_status"] == "failed"
    assert body["summary_error"] == "Gemini unavailable"
    assert body["patient_friendly_summary"] is None
    assert body["is_ai_generated"] is False

    set_llm_client(_RecordingLLM())
    retried = client.post(
        f"/api/appointments/{appointment['id']}/visit/summary/retry",
        headers=_auth_header(doctor_token),
    )
    assert retried.status_code == 200, retried.text
    retried_body = retried.json()
    assert retried_body["summary_status"] == "succeeded"
    assert retried_body["clinical_notes"] == CLINICAL_NOTES
    assert retried_body["medications"][0]["medicine_name"] == "Ibuprofen"
    assert retried_body["is_ai_generated"] is True


def test_only_assigned_doctor_can_submit_visit_notes(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    set_llm_client(_RecordingLLM())
    doctor_a = _create_doctor(admin_token)
    doctor_b = _create_doctor(admin_token)
    patient_token = _register_patient()
    appointment = _book(patient_token, doctor_a["id"])

    patient_submit = client.post(
        f"/api/appointments/{appointment['id']}/visit",
        json=VISIT_BODY,
        headers=_auth_header(patient_token),
    )
    assert patient_submit.status_code == 403

    admin_submit = client.post(
        f"/api/appointments/{appointment['id']}/visit",
        json=VISIT_BODY,
        headers=_auth_header(admin_token),
    )
    assert admin_submit.status_code == 403

    other_submit = client.post(
        f"/api/appointments/{appointment['id']}/visit",
        json=VISIT_BODY,
        headers=_auth_header(_doctor_token(doctor_b)),
    )
    assert other_submit.status_code == 403

    assigned = client.post(
        f"/api/appointments/{appointment['id']}/visit",
        json=VISIT_BODY,
        headers=_auth_header(_doctor_token(doctor_a)),
    )
    assert assigned.status_code == 201, assigned.text
