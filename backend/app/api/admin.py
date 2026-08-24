"""Admin-only routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.admin_doctors import router as doctors_router
from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models import User
from app.schemas.notification import NotificationLogPublic
from app.services.notifications import list_notification_logs

router = APIRouter()
router.include_router(doctors_router, prefix="/doctors", tags=["admin-doctors"])


@router.get("/dashboard")
def admin_dashboard(current_admin: User = Depends(get_current_admin)) -> dict[str, str]:
    return {
        "status": "ok",
        "service": "CareConnect",
        "role": current_admin.role,
    }


@router.get("/notifications", response_model=list[NotificationLogPublic])
def admin_list_notifications(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
    status: str | None = Query(default=None),
) -> list[NotificationLogPublic]:
    return [
        NotificationLogPublic.model_validate(row)
        for row in list_notification_logs(db, status=status)
    ]
