import csv
from io import StringIO
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from uuid import uuid4

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.schemas.users import UserProfile, UserRole
from app.core.permissions import MANAGEMENT_ROLES, require_roles
from app.schemas.tracking import TripRecord, TripRebuildResult
from app.services.trip_service import build_trips

router = APIRouter(prefix="/reports", tags=["reports"])


def _csv_response(
    rows: list[dict[str, Any]], columns: tuple[str, ...], filename: str
) -> Response:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _database() -> Any:
    try:
        return get_firebase_client().get_database()
    except FirebaseUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firestore is unavailable.",
        ) from exc


def _tenant_filter(query: Any, actor: UserProfile) -> Any:
    if actor.role == UserRole.SUPER_ADMIN:
        return query
    if not actor.tenant_id:
        raise HTTPException(status_code=403, detail="Your account is not assigned to a tenant.")
    return query.where("tenant_id", "==", actor.tenant_id)


@router.get("/device-status")
def device_status_report(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    query = _tenant_filter(_database().collection("device_status"), actor)
    return [
        {**(snapshot.to_dict() or {}), "device_id": snapshot.id}
        for snapshot in query.limit(limit).stream()
    ]


@router.get("/alerts")
def alert_report(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    start: datetime,
    end: datetime,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    if end < start or end - start > timedelta(days=90):
        raise HTTPException(
            status_code=422,
            detail="Provide a valid date range of no more than 90 days.",
        )
    query = _tenant_filter(_database().collection("alerts"), actor)
    query = query.where("event_timestamp", ">=", start).where(
        "event_timestamp", "<=", end
    )
    return [
        {**(snapshot.to_dict() or {}), "alert_id": snapshot.id}
        for snapshot in query.limit(limit).stream()
    ]


@router.get("/alerts.csv")
def alert_report_csv(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    start: datetime,
    end: datetime,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> Response:
    if end < start or end - start > timedelta(days=90):
        raise HTTPException(
            status_code=422,
            detail="Provide a valid date range of no more than 90 days.",
        )
    query = _tenant_filter(_database().collection("alerts"), actor)
    query = query.where("event_timestamp", ">=", start).where(
        "event_timestamp", "<=", end
    )
    rows = [
        {**(snapshot.to_dict() or {}), "alert_id": snapshot.id}
        for snapshot in query.limit(limit).stream()
    ]
    return _csv_response(
        rows,
        (
            "alert_id", "tenant_id", "device_id", "alert_type", "severity",
            "description", "event_timestamp", "status", "acknowledged_by",
            "acknowledged_at", "resolution_notes",
        ),
        "alerts.csv",
    )


@router.get("/location-history")
def location_history_report(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    device_id: str,
    start: datetime,
    end: datetime,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    if end < start or end - start > timedelta(days=90):
        raise HTTPException(
            status_code=422,
            detail="Provide a valid date range of no more than 90 days.",
        )
    database = _database()
    device = database.collection("devices").document(device_id).get()
    if not device.exists:
        raise HTTPException(status_code=404, detail="Device not found.")
    device_data = device.to_dict() or {}
    if actor.role != UserRole.SUPER_ADMIN and (
        not actor.tenant_id or device_data.get("tenant_id") != actor.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Device not found.")
    query = (
        database.collection("devices")
        .document(device_id)
        .collection("locations")
        .where("device_timestamp", ">=", start)
        .where("device_timestamp", "<=", end)
        .order_by("device_timestamp")
        .limit(limit)
    )
    return [
        {**(snapshot.to_dict() or {}), "event_id": snapshot.id}
        for snapshot in query.stream()
    ]


@router.get("/trips", response_model=list[TripRecord])
def trips_report(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    start: datetime,
    end: datetime,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    if end < start or end - start > timedelta(days=90):
        raise HTTPException(
            status_code=422,
            detail="Provide a valid date range of no more than 90 days.",
        )
    query = _tenant_filter(_database().collection("trips"), actor)
    query = (
        query.where("started_at", ">=", start)
        .where("started_at", "<=", end)
        .order_by("started_at")
        .limit(limit)
    )
    return [
        {**(snapshot.to_dict() or {}), "trip_id": snapshot.id}
        for snapshot in query.stream()
    ]


@router.post(
    "/trips/{device_id}/rebuild",
    response_model=TripRebuildResult,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def rebuild_device_trips(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
    start: datetime,
    end: datetime,
) -> TripRebuildResult:
    if end < start or end - start > timedelta(days=90):
        raise HTTPException(
            status_code=422,
            detail="Provide a valid date range of no more than 90 days.",
        )
    database = _database()
    device_snapshot = database.collection("devices").document(device_id).get()
    device = device_snapshot.to_dict() if device_snapshot.exists else None
    if not isinstance(device, dict) or device.get("deleted_at") is not None:
        raise HTTPException(status_code=404, detail="Device not found.")
    tenant_id = device.get("tenant_id")
    if actor.role != UserRole.SUPER_ADMIN and (
        not actor.tenant_id or tenant_id != actor.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Device not found.")
    if not isinstance(tenant_id, str):
        raise HTTPException(status_code=409, detail="Device tenant configuration is invalid.")

    snapshots = list(
        database.collection("devices")
        .document(device_id)
        .collection("locations")
        .where("device_timestamp", ">=", start)
        .where("device_timestamp", "<=", end)
        .order_by("device_timestamp")
        .limit(501)
        .stream()
    )
    truncated = len(snapshots) > 500
    snapshots = snapshots[:500]
    points = [
        {**(snapshot.to_dict() or {}), "event_id": snapshot.id}
        for snapshot in snapshots
    ]
    trips = build_trips(
        device_id,
        tenant_id,
        points,
        get_settings().trip_idle_gap_seconds,
        get_settings().trip_min_distance_meters,
    )
    batch = database.batch()
    for trip in trips:
        trip_ref = database.collection("trips").document(trip["trip_id"])
        batch.set(trip_ref, trip, merge=True)
    batch.create(
        database.collection("audit_logs").document(str(uuid4())),
        {
            "tenant_id": tenant_id,
            "actor_uid": actor.uid,
            "action": "trip.rebuild",
            "resource_type": "device",
            "resource_id": device_id,
            "timestamp": datetime.now(timezone.utc),
            "result": "success",
        },
    )
    batch.commit()
    return TripRebuildResult(
        device_id=device_id,
        points_processed=len(points),
        trips_written=len(trips),
        truncated=truncated,
    )


@router.get("/device-assignments")
def device_assignments_report(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    query = _tenant_filter(_database().collection("device_assignments"), actor)
    return [
        {**(snapshot.to_dict() or {}), "assignment_id": snapshot.id}
        for snapshot in query.limit(limit).stream()
    ]
