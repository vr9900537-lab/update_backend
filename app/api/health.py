from typing import Any

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.firebase import get_firebase_client

router = APIRouter()


@router.get("/health", tags=["health"])
def health_check() -> dict[str, Any]:
    """Report that the API process is responding."""
    settings = get_settings()
    firebase_client = get_firebase_client()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "firebase": firebase_client.status(),
    }
