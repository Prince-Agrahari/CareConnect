"""PostgreSQL exclusion-constraint verification for overlapping appointments."""

from datetime import UTC, datetime, timedelta
from threading import Thread
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models import Appointment, DoctorProfile, PatientProfile, User


def postgres_available() -> bool:
    try:
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not postgres_available(),
    reason="PostgreSQL is not available",
)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}@careconnect.test"


def _create_patient_and_doctor(session: Session) -> tuple[PatientProfile, DoctorProfile]:
    patient_user = User(
        email=_unique_email("patient"),
        hashed_password="hashed",
        full_name="Test Patient",
        role="patient",
    )
    doctor_user = User(
        email=_unique_email("doctor"),
        hashed_password="hashed",
        full_name="Test Doctor",
        role="doctor",
    )
    session.add_all([patient_user, doctor_user])
    session.flush()
    patient = PatientProfile(user_id=patient_user.id)
    doctor = DoctorProfile(
        user_id=doctor_user.id,
        specialization="General Medicine",
        slot_duration_minutes=30,
    )
    session.add_all([patient, doctor])
    session.flush()
    return patient, doctor


def test_overlapping_appointments_for_same_doctor_are_rejected() -> None:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    start = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)

    with SessionLocal() as session:
        patient, doctor = _create_patient_and_doctor(session)
        session.add(
            Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                start_datetime=start,
                end_datetime=end,
                status="confirmed",
                reason="First booking",
            )
        )
        session.commit()
        doctor_id = doctor.id
        patient_id = patient.id

    with SessionLocal() as session:
        session.add(
            Appointment(
                patient_id=patient_id,
                doctor_id=doctor_id,
                start_datetime=start + timedelta(minutes=15),
                end_datetime=end + timedelta(minutes=15),
                status="confirmed",
                reason="Overlapping booking",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        count = session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.doctor_id == doctor_id,
                Appointment.status == "confirmed",
            )
        )
        assert count == 1

    engine.dispose()


def test_adjacent_appointments_for_same_doctor_are_allowed() -> None:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    start = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    mid = start + timedelta(minutes=30)
    end = start + timedelta(minutes=60)

    with SessionLocal() as session:
        patient, doctor = _create_patient_and_doctor(session)
        session.add_all(
            [
                Appointment(
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    start_datetime=start,
                    end_datetime=mid,
                    status="confirmed",
                    reason="First slot",
                ),
                Appointment(
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    start_datetime=mid,
                    end_datetime=end,
                    status="confirmed",
                    reason="Adjacent slot",
                ),
            ]
        )
        session.commit()
        persisted = session.scalars(
            select(Appointment).where(Appointment.doctor_id == doctor.id)
        ).all()
        assert len(persisted) == 2

    engine.dispose()


def test_cancelled_appointment_does_not_block_new_booking() -> None:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    start = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)

    with SessionLocal() as session:
        patient, doctor = _create_patient_and_doctor(session)
        session.add(
            Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                start_datetime=start,
                end_datetime=end,
                status="cancelled",
                reason="Cancelled visit",
            )
        )
        session.commit()
        session.add(
            Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                start_datetime=start,
                end_datetime=end,
                status="confirmed",
                reason="Rebooked slot",
            )
        )
        session.commit()
        count = session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.doctor_id == doctor.id)
        )
        assert count == 2

    engine.dispose()


def test_concurrent_overlapping_inserts_allow_only_one_success() -> None:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    start = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)

    with SessionLocal() as session:
        patient_a, doctor = _create_patient_and_doctor(session)
        patient_b_user = User(
            email=_unique_email("patient"),
            hashed_password="hashed",
            full_name="Second Patient",
            role="patient",
        )
        session.add(patient_b_user)
        session.flush()
        patient_b = PatientProfile(user_id=patient_b_user.id)
        session.add(patient_b)
        session.commit()
        doctor_id = doctor.id
        patient_a_id = patient_a.id
        patient_b_id = patient_b.id

    results: list[str] = []

    def book(patient_id: int) -> None:
        with SessionLocal() as session:
            session.add(
                Appointment(
                    patient_id=patient_id,
                    doctor_id=doctor_id,
                    start_datetime=start,
                    end_datetime=end,
                    status="confirmed",
                    reason="Concurrent booking",
                )
            )
            try:
                session.commit()
                results.append("success")
            except IntegrityError:
                session.rollback()
                results.append("conflict")

    threads = [
        Thread(target=book, args=(patient_a_id,)),
        Thread(target=book, args=(patient_b_id,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count("success") == 1
    assert results.count("conflict") == 1
    engine.dispose()
