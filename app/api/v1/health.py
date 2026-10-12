from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.core.firebase import get_firebase_client

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "firebase": get_firebase_client().status(),
    }


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, Any]:
    firebase_status = get_firebase_client().status()
    if firebase_status["status"] != "connected":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Required Firebase services are unavailable.",
        )
    settings = get_settings()
    return {
        "status": "ready",
        "service": settings.app_name,
        "firebase": {
            "status": firebase_status["status"],
            "project_id": firebase_status["project_id"],
        },
    }
