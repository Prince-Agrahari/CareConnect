"""API v1 router."""

from fastapi import APIRouter

from app.api.v1 import health
from app.api.calendar import router as calendar_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(calendar_router, prefix="/calendar", tags=["calendar"])
