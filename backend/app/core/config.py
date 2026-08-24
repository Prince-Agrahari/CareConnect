"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Browser origins that must always be accepted. An empty CORS_ORIGINS env value
# (common when copying .env.example) would otherwise allow none.
REQUIRED_CORS_ORIGINS = (
    "http://localhost:5173",
    "https://careconnect-frontend-32l4.onrender.com",
)


def parse_cors_origins(raw: str | None) -> list[str]:
    text = (raw or "").strip().strip("\"'")
    origins: list[str] = []
    for part in text.split(","):
        origin = part.strip().strip("\"'").rstrip("/")
        if origin:
            origins.append(origin)
    for required in REQUIRED_CORS_ORIGINS:
        if required not in origins:
            origins.append(required)
    return origins


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "CareConnect"
    APP_ENV: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = ",".join(REQUIRED_CORS_ORIGINS)

    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/careconnect"

    JWT_SECRET_KEY: str = "replace-with-a-long-random-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    SENDGRID_API_KEY: str = ""
    SENDGRID_FROM_EMAIL: str = ""

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/calendar/callback"
    GOOGLE_OAUTH_SUCCESS_REDIRECT: str = "http://localhost:5173/?calendar=connected"
    GOOGLE_OAUTH_FAILURE_REDIRECT: str = "http://localhost:5173/?calendar=error"

    SLOT_HOLD_MINUTES: int = 5
    NOTIFICATION_MAX_RETRIES: int = 5
    NOTIFICATION_RETRY_BASE_SECONDS: int = 60
    APPOINTMENT_REMINDER_HOURS: int = 24

    @property
    def cors_origin_list(self) -> list[str]:
        return parse_cors_origins(self.CORS_ORIGINS)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
