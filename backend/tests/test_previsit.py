"""Patient symptoms and Gemini pre-visit summary tests."""

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
from app.services.previsit import PREVISIT_PROMPT_TEMPLATE, build_previsit_prompt, parse_previsit_response

client = TestClient(app)

MONDAY_START = "2026-09-07T09:00:00+00:00"
MONDAY_END = "2026-09-07T09:30:00+00:00"
SLOT = {"start_datetime": MONDAY_START, "end_datetime": MONDAY_END}
SYMPTOMS = "Headache for three days, worse in the morning, with some nausea."
SUCCESS_PAYLOAD = {
    "urgency_level": "Medium",
    "chief_complaint": "Persistent morning headache with nausea",
    "suggested_questions": [
        "When did the headache start?",
        "Have you taken any medication?",
        "Any vision changes or vomiting?",
    ],
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
        json={"email": email, "password": "securepass1", "full_name": "Symptom Patient"},
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
            "full_name": "Dr Previsit",
            "specialization": "General Medicine",
            "slot_duration_minutes": 30,
            "working_hours": [{"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00"}],
        },
        headers=_auth_header(admin_token),
    )
    assert response.status_code == 201
    return response.json()


def _hold(token: str, doctor_id: int) -> object:
    return client.post(
        "/api/appointments/hold",
        json={"doctor_id": doctor_id, **SLOT},
        headers=_auth_header(token),
    )


def _confirm(token: str, hold_id: int, symptoms: str = SYMPTOMS) -> object:
    return client.post(
        "/api/appointments/confirm",
        json={"hold_id": hold_id, "reason": "Checkup", "symptoms": symptoms},
        headers=_auth_header(token),
    )


class _RecordingLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text


class _FailingLLM:
    def generate(self, prompt: str) -> str:
        raise LLMError("Gemini unavailable")


class _TimeoutLLM:
    def generate(self, prompt: str) -> str:
        raise LLMError("Gemini request timed out")


def test_parse_previsit_json_success() -> None:
    parsed = parse_previsit_response(json.dumps(SUCCESS_PAYLOAD))
    assert parsed.urgency_level == "Medium"
    assert parsed.chief_complaint == SUCCESS_PAYLOAD["chief_complaint"]
    assert parsed.suggested_questions == SUCCESS_PAYLOAD["suggested_questions"]


def test_parse_previsit_rejects_invalid_urgency() -> None:
    with pytest.raises(ValueError, match="urgency"):
        parse_previsit_response(
            json.dumps({**SUCCESS_PAYLOAD, "urgency_level": "Critical"})
        )


def test_parse_previsit_rejects_wrong_question_count() -> None:
    with pytest.raises(ValueError, match="three"):
        parse_previsit_response(
            json.dumps({**SUCCESS_PAYLOAD, "suggested_questions": ["Only one?"]})
        )


def test_build_previsit_prompt_matches_documented_template() -> None:
    prompt = build_previsit_prompt(SYMPTOMS)
    assert prompt == PREVISIT_PROMPT_TEMPLATE.format(symptoms=SYMPTOMS)
    assert prompt.startswith("Analyse these symptoms and return:")
    assert prompt.endswith(SYMPTOMS)


def test_confirm_requires_symptoms(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    doctor = _create_doctor(admin_token)
    token = _register_patient()
    hold = _hold(token, doctor["id"])
    missing = client.post(
        "/api/appointments/confirm",
        json={"hold_id": hold.json()["id"], "reason": "Checkup"},
        headers=_auth_header(token),
    )
    assert missing.status_code == 422
    blank = _confirm(token, hold.json()["id"], symptoms="   ")
    assert blank.status_code == 422


def test_successful_gemini_summary_is_stored(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    llm = _RecordingLLM(json.dumps(SUCCESS_PAYLOAD))
    set_llm_client(llm)
    doctor = _create_doctor(admin_token)
    token = _register_patient()
    hold = _hold(token, doctor["id"])
    confirmed = _confirm(token, hold.json()["id"])
    assert confirmed.status_code == 201, confirmed.text
    appointment_id = confirmed.json()["id"]
    assert llm.prompts == [build_previsit_prompt(SYMPTOMS)]

    summary = client.get(
        f"/api/appointments/{appointment_id}/previsit-summary",
        headers=_auth_header(token),
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["symptoms"] == SYMPTOMS
    assert body["status"] == "succeeded"
    assert body["urgency_level"] == "Medium"
    assert body["chief_complaint"] == SUCCESS_PAYLOAD["chief_complaint"]
    assert body["suggested_questions"] == SUCCESS_PAYLOAD["suggested_questions"]
    assert body["error_message"] is None
    assert body["generated_at"] is not None
    assert body["raw_response"] is None
    assert "not a medical diagnosis" in body["disclaimer"]

    doctor_login = client.post(
        "/api/auth/login",
        json={"email": doctor["email"], "password": "securepass1"},
    )
    doctor_view = client.get(
        f"/api/appointments/{appointment_id}/previsit-summary",
        headers=_auth_header(doctor_login.json()["access_token"]),
    )
    assert doctor_view.status_code == 200
    assert doctor_view.json()["raw_response"] == json.dumps(SUCCESS_PAYLOAD)
    assert doctor_view.json()["symptoms"] == SYMPTOMS


def test_failed_gemini_does_not_break_booking(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    set_llm_client(_FailingLLM())
    doctor = _create_doctor(admin_token)
    token = _register_patient()
    hold = _hold(token, doctor["id"])
    confirmed = _confirm(token, hold.json()["id"])
    assert confirmed.status_code == 201, confirmed.text
    appointment = confirmed.json()
    assert appointment["status"] == "confirmed"

    summary = client.get(
        f"/api/appointments/{appointment['id']}/previsit-summary",
        headers=_auth_header(token),
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["symptoms"] == SYMPTOMS
    assert body["status"] == "failed"
    assert body["error_message"] == "Gemini unavailable"
    assert body["urgency_level"] is None
    assert body["chief_complaint"] is None
    assert body["suggested_questions"] is None
    assert body["generated_at"] is not None

    doctor_login = client.post(
        "/api/auth/login",
        json={"email": doctor["email"], "password": "securepass1"},
    )
    doctor_view = client.get(
        f"/api/appointments/{appointment['id']}/previsit-summary",
        headers=_auth_header(doctor_login.json()["access_token"]),
    )
    assert doctor_view.status_code == 200
    assert doctor_view.json()["symptoms"] == SYMPTOMS
    assert doctor_view.json()["status"] == "failed"

    set_llm_client(_RecordingLLM(json.dumps(SUCCESS_PAYLOAD)))
    retried = client.post(
        f"/api/appointments/{appointment['id']}/previsit-summary/retry",
        headers=_auth_header(token),
    )
    assert retried.status_code == 200
    retried_body = retried.json()
    assert retried_body["status"] == "succeeded"
    assert retried_body["urgency_level"] == "Medium"
    assert retried_body["symptoms"] == SYMPTOMS
    assert retried_body["error_message"] is None


def test_invalid_gemini_response_marks_generation_failed(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    set_llm_client(_RecordingLLM("I cannot produce a structured summary."))
    doctor = _create_doctor(admin_token)
    token = _register_patient()
    hold = _hold(token, doctor["id"])
    confirmed = _confirm(token, hold.json()["id"])
    assert confirmed.status_code == 201
    summary = client.get(
        f"/api/appointments/{confirmed.json()['id']}/previsit-summary",
        headers=_auth_header(token),
    )
    body = summary.json()
    assert body["status"] == "failed"
    assert body["symptoms"] == SYMPTOMS
    assert body["error_message"]


def test_gemini_timeout_does_not_break_booking(
    admin_token: str,
    before_monday_hours: datetime,
) -> None:
    set_llm_client(_TimeoutLLM())
    doctor = _create_doctor(admin_token)
    token = _register_patient()
    hold = _hold(token, doctor["id"])
    confirmed = _confirm(token, hold.json()["id"])
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    summary = client.get(
        f"/api/appointments/{confirmed.json()['id']}/previsit-summary",
        headers=_auth_header(token),
    )
    body = summary.json()
    assert body["status"] == "failed"
    assert body["error_message"] == "Gemini request timed out"
    assert body["symptoms"] == SYMPTOMS


def test_gemini_client_maps_timeout_to_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations import gemini as gemini_mod
    from app.integrations.gemini import GeminiLLMClient

    monkeypatch.setattr(gemini_mod.settings, "GEMINI_API_KEY", "test-key")

    class _TimeoutModel:
        def generate_content(self, prompt: str, request_options: dict | None = None) -> object:
            assert request_options == {"timeout": gemini_mod.GEMINI_TIMEOUT_SECONDS}
            raise TimeoutError("deadline exceeded")

    monkeypatch.setattr(gemini_mod.genai, "configure", lambda **kwargs: None)
    monkeypatch.setattr(gemini_mod.genai, "GenerativeModel", lambda **kwargs: _TimeoutModel())
    with pytest.raises(LLMError, match="timed out"):
        GeminiLLMClient().generate("hello")
