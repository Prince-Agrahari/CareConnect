"""Google Calendar OAuth connect, callback, status, and disconnect."""

from __future__ import annotations

from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import InvalidTokenError
from app.integrations.calendar import CalendarError
from app.integrations.google_oauth import (
    GoogleOAuthTokens,
    build_authorization_url,
    create_oauth_state,
    exchange_authorization_code,
    parse_oauth_state,
)
from app.models import CalendarIntegration, User
from app.models.enums import CalendarProvider
from app.schemas.calendar import CalendarConnectResponse, CalendarStatusResponse
from app.services.errors import ServiceError


def _success_redirect() -> str:
    return settings.GOOGLE_OAUTH_SUCCESS_REDIRECT


def _failure_redirect(reason: str) -> str:
    base = settings.GOOGLE_OAUTH_FAILURE_REDIRECT
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}reason={reason}"


def start_google_connect(user: User) -> CalendarConnectResponse:
    try:
        state = create_oauth_state(user.id)
        url = build_authorization_url(state)
    except CalendarError as exc:
        raise ServiceError(status_code=503, detail=str(exc)) from exc
    return CalendarConnectResponse(authorization_url=url)


def calendar_status(db: Session, user: User) -> CalendarStatusResponse:
    integration = db.scalar(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user.id,
            CalendarIntegration.provider == CalendarProvider.GOOGLE,
        )
    )
    if integration is None or not integration.is_connected:
        return CalendarStatusResponse(connected=False, provider="google")
    return CalendarStatusResponse(
        connected=True,
        provider="google",
        google_calendar_id=integration.google_calendar_id or "primary",
    )


def save_google_tokens(db: Session, user_id: int, tokens: GoogleOAuthTokens) -> CalendarIntegration:
    integration = db.scalar(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user_id,
            CalendarIntegration.provider == CalendarProvider.GOOGLE,
        )
    )
    if integration is None:
        integration = CalendarIntegration(
            user_id=user_id,
            provider=CalendarProvider.GOOGLE,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            token_expiry=tokens.expiry,
            google_calendar_id="primary",
            scopes=tokens.scopes,
            is_connected=True,
        )
        db.add(integration)
    else:
        integration.access_token = tokens.access_token
        integration.refresh_token = tokens.refresh_token
        integration.token_expiry = tokens.expiry
        integration.google_calendar_id = integration.google_calendar_id or "primary"
        if tokens.scopes:
            integration.scopes = tokens.scopes
        integration.is_connected = True
    db.commit()
    db.refresh(integration)
    return integration


def complete_google_callback(db: Session, code: str | None, state: str | None, error: str | None) -> RedirectResponse:
    if error:
        return RedirectResponse(url=_failure_redirect("denied"), status_code=302)
    if not code or not state:
        return RedirectResponse(url=_failure_redirect("missing_code"), status_code=302)
    try:
        user_id = parse_oauth_state(state)
        tokens = exchange_authorization_code(code)
        save_google_tokens(db, user_id, tokens)
    except (InvalidTokenError, CalendarError, ValueError):
        return RedirectResponse(url=_failure_redirect("oauth_failed"), status_code=302)
    return RedirectResponse(url=_success_redirect(), status_code=302)


def disconnect_google_calendar(db: Session, user: User) -> CalendarStatusResponse:
    integration = db.scalar(
        select(CalendarIntegration).where(
            CalendarIntegration.user_id == user.id,
            CalendarIntegration.provider == CalendarProvider.GOOGLE,
        )
    )
    if integration is not None:
        integration.is_connected = False
        integration.access_token = ""
        integration.refresh_token = ""
        integration.token_expiry = None
        db.commit()
    return CalendarStatusResponse(connected=False, provider="google")
