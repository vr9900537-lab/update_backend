import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.cloud.firestore_v1 import FieldFilter

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import OPERATIONS_ROLES, require_roles
from app.schemas.tracking import (
    DeviceEventIngestResult,
    LocationIngest,
    LocationIngestResult,
    LocationPage,
    LocationRecord,
    SimulatedDeviceEvent,
)
from app.schemas.users import UserProfile, UserRole
from app.services.location_service import ingest_location
from app.services.device_event_service import ingest_simulated_event
from app.websockets.manager import manager as websocket_manager

router = APIRouter(tags=["tracking"])
ingestion_router = APIRouter(prefix="/ingestion", tags=["device ingestion"])


def _db() -> Any:
    try:
        return get_firebase_client().get_database()
    except FirebaseUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firestore is unavailable.",
        ) from exc


def _device_for_user(database: Any, device_id: str, user: UserProfile) -> dict[str, Any]:
    snapshot = database.collection("devices").document(device_id).get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Device not found.")
    data = snapshot.to_dict() or {}
    if data.get("deleted_at") is not None:
        raise HTTPException(status_code=404, detail="Device not found.")
    if user.role != UserRole.SUPER_ADMIN and (
        not user.tenant_id or data.get("tenant_id") != user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Device not found.")
    return data


@ingestion_router.post(
    "/simulated",
    response_model=LocationIngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_roles(*OPERATIONS_ROLES))],
)
async def ingest_simulated_location(
    payload: LocationIngest,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> LocationIngestResult:
    settings = get_settings()
    if not settings.simulated_ingestion_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Simulated location ingestion is disabled.",
        )
    database = _db()
    device = _device_for_user(database, payload.device_id, actor)
    tenant_id = device.get("tenant_id")
    if not isinstance(tenant_id, str):
        raise HTTPException(status_code=409, detail="Device tenant configuration is invalid.")
    result = await asyncio.to_thread(
        ingest_location, database, payload, tenant_id, actor.uid
    )
    if not result["duplicate"] and result["updated_latest"]:
        await websocket_manager.publish(
            tenant_id,
            {
                "type": "location.updated",
                "device_id": payload.device_id,
                "latitude": payload.latitude,
                "longitude": payload.longitude,
                "accuracy_meters": payload.accuracy_meters,
                "device_timestamp": payload.device_timestamp.isoformat(),
                "source": "simulated",
            },
        )
    return LocationIngestResult.model_validate(result)


@ingestion_router.post(
    "/simulated/events",
    response_model=DeviceEventIngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_roles(*OPERATIONS_ROLES))],
)
async def ingest_simulated_device_event(
    payload: SimulatedDeviceEvent,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceEventIngestResult:
    if not get_settings().simulated_ingestion_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Simulated device-event ingestion is disabled.",
        )
    database = _db()
    device = _device_for_user(database, payload.device_id, actor)
    tenant_id = device.get("tenant_id")
    if not isinstance(tenant_id, str):
        raise HTTPException(status_code=409, detail="Device tenant configuration is invalid.")
    result = await asyncio.to_thread(
        ingest_simulated_event, database, payload, tenant_id, actor.uid
    )
    if not result["duplicate"]:
        event: dict[str, Any] = {
            "type": f"device.{payload.event_type}",
            "device_id": payload.device_id,
            "device_timestamp": payload.device_timestamp.isoformat(),
            "source": "simulated",
        }
        if result.get("alert_id"):
            event["alert_id"] = result["alert_id"]
        await websocket_manager.publish(tenant_id, event)
    return DeviceEventIngestResult.model_validate(result)


@router.get("/tracking/live", response_model=list[LocationRecord])
def get_live_locations(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[LocationRecord]:
    database = _db()
    query = database.collection("latest_locations")
    if actor.role != UserRole.SUPER_ADMIN:
        if not actor.tenant_id:
            raise HTTPException(status_code=403, detail="Your account is not assigned to a tenant.")
        query = query.where(filter=FieldFilter("tenant_id", "==", actor.tenant_id))
    result: list[LocationRecord] = []
    for snapshot in query.limit(limit).stream():
        try:
            result.append(
                LocationRecord.model_validate(
                    {**(snapshot.to_dict() or {}), "device_id": snapshot.id}
                )
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="A stored location record is invalid.",
            ) from exc
    return result


@router.get(
    "/tracking/devices/{device_id}/latest",
    response_model=LocationRecord,
)
def get_latest_location(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> LocationRecord:
    database = _db()
    _device_for_user(database, device_id, actor)
    snapshot = database.collection("latest_locations").document(device_id).get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="No location has been reported for this device.")
    return LocationRecord.model_validate(
        {**(snapshot.to_dict() or {}), "device_id": device_id}
    )


@router.get(
    "/tracking/devices/{device_id}/history",
    response_model=LocationPage,
)
def get_location_history(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    start: datetime | None = None,
    end: datetime | None = None,
    cursor: str | None = Query(default=None, max_length=128),
) -> LocationPage:
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start must be earlier than end.")
    if start and end and end - start > timedelta(days=90):
        raise HTTPException(status_code=422, detail="Date range cannot exceed 90 days.")

    database = _db()
    _device_for_user(database, device_id, actor)
    query = (
        database.collection("devices")
        .document(device_id)
        .collection("locations")
    )
    query = query.order_by("device_timestamp")
    if start:
        query = query.where("device_timestamp", ">=", start)
    if end:
        query = query.where("device_timestamp", "<=", end)
    if cursor:
        cursor_snapshot = (
            database.collection("devices")
            .document(device_id)
            .collection("locations")
            .document(cursor)
            .get()
        )
        if not cursor_snapshot.exists:
            raise HTTPException(status_code=400, detail="Invalid history cursor.")
        query = query.start_after(cursor_snapshot)
    snapshots = list(query.limit(limit + 1).stream())
    has_more = len(snapshots) > limit
    snapshots = snapshots[:limit]
    items = [
        LocationRecord.model_validate(
            {**(snapshot.to_dict() or {}), "device_id": device_id}
        )
        for snapshot in snapshots
    ]
    return LocationPage(
        items=items,
        next_cursor=snapshots[-1].id if has_more and snapshots else None,
    )


@router.get(
    "/tracking/devices/{device_id}/playback",
    response_model=list[LocationRecord],
)
def get_location_playback(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
    start: datetime,
    end: datetime,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> list[LocationRecord]:
    """Return a bounded, chronological slice suitable for route playback."""
    if start > end or end - start > timedelta(days=90):
        raise HTTPException(
            status_code=422,
            detail="Provide a valid date range of no more than 90 days.",
        )
    database = _db()
    _device_for_user(database, device_id, actor)
    snapshots = (
        database.collection("devices")
        .document(device_id)
        .collection("locations")
        .where("device_timestamp", ">=", start)
        .where("device_timestamp", "<=", end)
        .order_by("device_timestamp")
        .limit(limit)
        .stream()
    )
    return [
        LocationRecord.model_validate(
            {**(snapshot.to_dict() or {}), "device_id": device_id}
        )
        for snapshot in snapshots
    ]


@router.get("/tracking/devices/{device_id}/status")
def get_tracking_status(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> dict[str, Any]:
    database = _db()
    _device_for_user(database, device_id, actor)
    snapshot = database.collection("device_status").document(device_id).get()
    if not snapshot.exists:
        return {
            "device_id": device_id,
            "connectivity_status": "unknown",
            "last_seen_at": None,
            "location_freshness": "unavailable",
        }

    data = snapshot.to_dict() or {}
    last_seen = data.get("last_seen_at")
    timeout = get_settings().device_online_timeout_seconds
    if last_seen is None:
        connectivity = "unknown"
    else:
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        connectivity = (
            "online"
            if (datetime.now(timezone.utc) - last_seen).total_seconds() <= timeout
            else "offline"
        )
    location = database.collection("latest_locations").document(device_id).get()
    latest_data = location.to_dict() if location.exists else None
    if not latest_data:
        freshness = "unavailable"
    else:
        recorded_at = latest_data["device_timestamp"]
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        freshness = (
            "fresh"
            if (datetime.now(timezone.utc) - recorded_at).total_seconds() <= timeout
            else "stale"
        )
    return {
        "device_id": device_id,
        "connectivity_status": connectivity,
        "battery_level": data.get("battery_level"),
        "last_seen_at": data.get("last_seen_at"),
        "location_freshness": freshness,
    }
