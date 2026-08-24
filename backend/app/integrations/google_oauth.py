"""Google OAuth 2.0 helpers. Tokens never leave the backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import InvalidTokenError
from app.integrations.calendar import CalendarError

GOOGLE_CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
OAUTH_STATE_PURPOSE = "google_calendar_oauth"


@dataclass(frozen=True)
class GoogleOAuthTokens:
    access_token: str
    refresh_token: str
    expiry: datetime | None
    scopes: str | None


def _client_config() -> dict:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise CalendarError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not configured")
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }


def _flow() -> Flow:
    flow = Flow.from_client_config(_client_config(), scopes=list(GOOGLE_CALENDAR_SCOPES))
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


def create_oauth_state(user_id: int) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=10)
    return jwt.encode(
        {
            "sub": str(user_id),
            "purpose": OAUTH_STATE_PURPOSE,
            "exp": expire,
            "iat": datetime.now(UTC),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def parse_oauth_state(state: str) -> int:
    try:
        payload = jwt.decode(state, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise InvalidTokenError("Invalid OAuth state") from exc
    if payload.get("purpose") != OAUTH_STATE_PURPOSE:
        raise InvalidTokenError("Invalid OAuth state")
    subject = payload.get("sub")
    if not subject:
        raise InvalidTokenError("Invalid OAuth state")
    return int(subject)


def build_authorization_url(state: str) -> str:
    flow = _flow()
    url, _generated_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return url


def exchange_authorization_code(code: str) -> GoogleOAuthTokens:
    try:
        flow = _flow()
        flow.fetch_token(code=code)
        credentials = flow.credentials
    except CalendarError:
        raise
    except Exception as exc:
        raise CalendarError(str(exc) or "Google OAuth token exchange failed") from exc
    refresh_token = credentials.refresh_token
    if not refresh_token:
        raise CalendarError(
            "Google did not return a refresh token. Disconnect and reconnect, granting offline access."
        )
    expiry = credentials.expiry
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    scopes = " ".join(credentials.scopes) if credentials.scopes else " ".join(GOOGLE_CALENDAR_SCOPES)
    return GoogleOAuthTokens(
        access_token=str(credentials.token),
        refresh_token=str(refresh_token),
        expiry=expiry,
        scopes=scopes,
    )


def refresh_access_token(
    *,
    access_token: str,
    refresh_token: str,
    expiry: datetime | None,
    now: datetime,
) -> GoogleOAuthTokens:
    if expiry is None or expiry > now + timedelta(minutes=2):
        return GoogleOAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expiry=expiry,
            scopes=None,
        )
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        expiry=expiry.replace(tzinfo=None) if expiry is not None else None,
    )
    try:
        credentials.refresh(Request())
    except Exception as exc:
        raise CalendarError(str(exc) or "Google OAuth token refresh failed") from exc
    new_expiry = credentials.expiry
    if new_expiry is not None and new_expiry.tzinfo is None:
        new_expiry = new_expiry.replace(tzinfo=UTC)
    return GoogleOAuthTokens(
        access_token=str(credentials.token),
        refresh_token=str(credentials.refresh_token or refresh_token),
        expiry=new_expiry,
        scopes=None,
    )
