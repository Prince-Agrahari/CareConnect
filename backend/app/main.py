"""CareConnect FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.appointments import router as appointments_router
from app.api.auth import router as auth_router
from app.api.doctors import router as doctors_router
from app.api.me import router as me_router
from app.api.v1.router import api_router
from app.core.config import settings

PLACEHOLDER_JWT_SECRET = "replace-with-a-long-random-secret"


def _assert_runtime_secrets() -> None:
    if settings.APP_ENV == "production" and settings.JWT_SECRET_KEY == PLACEHOLDER_JWT_SECRET:
        raise RuntimeError("JWT_SECRET_KEY must be set before running in production")


def create_app() -> FastAPI:
    _assert_runtime_secrets()
    application = FastAPI(
        title=settings.APP_NAME,
        description="Healthcare Appointment & Follow-up Manager",
        version="0.1.0",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)
    application.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    application.include_router(admin_router, prefix="/api/admin", tags=["admin"])
    application.include_router(me_router, prefix="/api/me", tags=["me"])
    application.include_router(doctors_router, prefix="/api/doctors", tags=["doctors"])
    application.include_router(appointments_router, prefix="/api/appointments", tags=["appointments"])

    @application.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.APP_NAME,
            "message": "CareConnect API is running",
        }

    return application


app = create_app()
