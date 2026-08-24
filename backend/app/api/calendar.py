"""Google Calendar OAuth routes. Tokens are never returned to the client."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.calendar import CalendarConnectResponse, CalendarStatusResponse
from app.services.calendar_oauth import (
    calendar_status,
    complete_google_callback,
    disconnect_google_calendar,
    start_google_connect,
)
from app.services.errors import ServiceError

router = APIRouter()


@router.get("/connect", response_model=CalendarConnectResponse)
def connect_google_calendar(current_user: User = Depends(get_current_user)) -> CalendarConnectResponse:
    try:
        return start_google_connect(current_user)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/callback")
def google_calendar_callback(
    db: Session = Depends(get_db),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    return complete_google_callback(db, code, state, error)


@router.get("/status", response_model=CalendarStatusResponse)
def read_calendar_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalendarStatusResponse:
    return calendar_status(db, current_user)


@router.post("/disconnect", response_model=CalendarStatusResponse)
def disconnect_calendar(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalendarStatusResponse:
    return disconnect_google_calendar(db, current_user)
