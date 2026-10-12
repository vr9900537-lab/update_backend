from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    assignments,
    auth,
    devices,
    device_groups,
    geofences,
    health,
    ingestion,
    management,
    persons,
    reports,
    tracking,
    users,
)
from app.websockets.router import router as websocket_router

router = APIRouter()
for module in (
    auth,
    users,
    devices,
    device_groups,
    assignments,
    ingestion,
    management,
    persons,
    tracking,
    geofences,
    alerts,
    reports,
    health,
):
    router.include_router(module.router)
router.include_router(websocket_router)
