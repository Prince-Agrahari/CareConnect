"""Authentication and user account services."""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.security import hash_password, verify_password
from app.models import PatientProfile, User
from app.models.enums import UserRole
from app.schemas.auth import UserRegister

logger = logging.getLogger(__name__)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.patient_profile),
            selectinload(User.doctor_profile),
        )
    )


def create_patient_user(db: Session, payload: UserRegister) -> User:
    email = normalize_email(payload.email)
    try:
        if get_user_by_email(db, email) is not None:
            raise ValueError("Email already registered")

        user = User(
            email=email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name.strip(),
            role=UserRole.PATIENT.value,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(PatientProfile(user_id=user.id))
        db.commit()
        db.refresh(user)
        return user
    except ValueError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Email already registered") from exc
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Registration failed")
        raise


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


def create_user_with_role(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    role: UserRole,
) -> User:
    """Create a non-public account. Used by admins and tests, not by public registration."""
    user = User(
        email=normalize_email(email),
        hashed_password=hash_password(password),
        full_name=full_name.strip(),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
