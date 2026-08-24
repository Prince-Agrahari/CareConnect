"""Model registry tests that do not require PostgreSQL."""

from app.db.base import Base
from app.models import (
    AISymptomSummary,
    Appointment,
    AppointmentSlotHold,
    CalendarEvent,
    CalendarIntegration,
    DoctorLeave,
    DoctorProfile,
    DoctorWorkingHours,
    MedicationReminder,
    NotificationLog,
    PatientProfile,
    Prescription,
    PrescriptionMedication,
    SymptomSubmission,
    User,
    VisitNote,
)

REQUIRED_TABLES = {
    "users",
    "patient_profiles",
    "doctor_profiles",
    "doctor_working_hours",
    "doctor_leaves",
    "appointments",
    "appointment_slot_holds",
    "symptom_submissions",
    "ai_symptom_summaries",
    "visit_notes",
    "prescriptions",
    "prescription_medications",
    "medication_reminders",
    "notification_logs",
    "calendar_integrations",
    "calendar_events",
}


def test_all_required_tables_are_registered() -> None:
    assert REQUIRED_TABLES == set(Base.metadata.tables.keys())


def test_appointment_has_required_columns() -> None:
    columns = set(Appointment.__table__.columns.keys())
    assert {
        "patient_id",
        "doctor_id",
        "start_datetime",
        "end_datetime",
        "status",
        "reason",
        "created_at",
        "updated_at",
    }.issubset(columns)


def test_slot_hold_has_required_columns() -> None:
    columns = set(AppointmentSlotHold.__table__.columns.keys())
    assert {
        "patient_id",
        "doctor_id",
        "start_datetime",
        "end_datetime",
        "expires_at",
        "status",
    }.issubset(columns)


def test_overlap_exclusion_constraints_exist() -> None:
    appointment_names = {constraint.name for constraint in Appointment.__table__.constraints}
    hold_names = {constraint.name for constraint in AppointmentSlotHold.__table__.constraints}
    leave_names = {constraint.name for constraint in DoctorLeave.__table__.constraints}
    hours_names = {constraint.name for constraint in DoctorWorkingHours.__table__.constraints}
    assert "ex_appointments_doctor_overlap" in appointment_names
    assert "ex_slot_holds_doctor_overlap" in hold_names
    assert "ex_doctor_leaves_no_overlap" in leave_names
    assert "ex_doctor_working_hours_no_overlap" in hours_names


def test_model_imports() -> None:
    assert User.__tablename__ == "users"
    assert PatientProfile.__tablename__ == "patient_profiles"
    assert DoctorProfile.__tablename__ == "doctor_profiles"
    assert DoctorWorkingHours.__tablename__ == "doctor_working_hours"
    assert SymptomSubmission.__tablename__ == "symptom_submissions"
    assert AISymptomSummary.__tablename__ == "ai_symptom_summaries"
    assert VisitNote.__tablename__ == "visit_notes"
    assert Prescription.__tablename__ == "prescriptions"
    assert PrescriptionMedication.__tablename__ == "prescription_medications"
    assert MedicationReminder.__tablename__ == "medication_reminders"
    assert NotificationLog.__tablename__ == "notification_logs"
    assert CalendarIntegration.__tablename__ == "calendar_integrations"
    assert CalendarEvent.__tablename__ == "calendar_events"


def test_alembic_config_resolves_backend_paths() -> None:
    from pathlib import Path

    from app.db.migrate import _alembic_config

    config = _alembic_config()
    script = Path(config.get_main_option("script_location"))
    assert (script / "env.py").is_file()
    assert (script / "versions" / "0001_initial_schema.py").is_file()
    assert (script / "versions" / "0002_working_hours_overlap.py").is_file()
    assert (script / "versions" / "0003_visit_follow_up_instructions.py").is_file()


def test_0002_checks_pg_constraint_before_ddl() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0002_working_hours_overlap.py"
    ).read_text(encoding="utf-8")
    assert "pg_constraint" in source
    assert "ex_doctor_working_hours_no_overlap" in source
    assert "duplicate_object" not in source
    assert "EXCEPTION" not in source
    assert "drop_all" not in source
    assert "DROP TABLE" not in source
    assert "DROP DATABASE" not in source
    assert "DROP CONSTRAINT" not in source
    assert "Base.metadata.drop_all" not in source
