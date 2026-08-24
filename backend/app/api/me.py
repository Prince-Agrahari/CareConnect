"""Current-user resources. Backend authorization remains authoritative."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_patient
from app.db.session import get_db
from app.models import User
from app.schemas.visit import MedicationReminderPublic
from app.services.appointments import require_patient_profile
from app.services.errors import ServiceError
from app.services.reminders import list_patient_medication_reminders

router = APIRouter()


@router.get("/medication-reminders", response_model=list[MedicationReminderPublic])
def read_my_medication_reminders(
    db: Session = Depends(get_db),
    current_patient: User = Depends(get_current_patient),
) -> list[MedicationReminderPublic]:
    try:
        profile = require_patient_profile(current_patient)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    rows = list_patient_medication_reminders(db, profile.id)
    return [
        MedicationReminderPublic(
            id=row.id,
            medicine_name=row.medication.medicine_name if row.medication else "",
            dosage=row.medication.dosage if row.medication else "",
            frequency=row.medication.frequency if row.medication else "",
            duration=row.medication.duration if row.medication else "",
            instructions=row.medication.instructions if row.medication else None,
            remind_at=row.remind_at,
            start_date=row.start_date,
            end_date=row.end_date,
            next_scheduled_at=row.next_scheduled_at,
            status=row.status,
        )
        for row in rows
    ]
