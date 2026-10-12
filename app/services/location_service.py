from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from firebase_admin import firestore
from fastapi import HTTPException, status

from app.schemas.tracking import LocationIngest
from app.services.notifications import record_mock_notification
from app.utils.geo import haversine_meters, polygon_relation


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ingest_location(
    database: Any,
    payload: LocationIngest,
    tenant_id: str,
    actor_uid: str,
) -> dict[str, bool | str]:
    recorded_at = _utc(payload.device_timestamp)
    now = datetime.now(timezone.utc)
    if recorded_at > now + timedelta(minutes=5):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Device timestamp is too far in the future.",
        )

    device_ref = database.collection("devices").document(payload.device_id)
    device_snapshot = device_ref.get()
    if not device_snapshot.exists:
        raise HTTPException(status_code=404, detail="Device not found.")
    device = device_snapshot.to_dict() or {}
    if device.get("tenant_id") != tenant_id or device.get("status") != "active":
        raise HTTPException(status_code=404, detail="Device not found.")

    event_ref = (
        device_ref.collection("locations")
        .document(payload.event_id)
    )
    latest_ref = database.collection("latest_locations").document(payload.device_id)
    status_ref = database.collection("device_status").document(payload.device_id)
    location_data = {
        **payload.model_dump(exclude={"device_timestamp"}),
        "tenant_id": tenant_id,
        "device_timestamp": recorded_at,
        "received_at": now,
        "source": "simulated",
    }
    transaction = database.transaction()

    @firestore.transactional
    def persist(transaction: Any) -> dict[str, bool | str]:
        event_snapshot = event_ref.get(transaction=transaction)
        if event_snapshot.exists:
            return {
                "accepted": True,
                "duplicate": True,
                "updated_latest": False,
                "event_id": payload.event_id,
            }

        latest_snapshot = latest_ref.get(transaction=transaction)
        latest_data = latest_snapshot.to_dict() or {} if latest_snapshot.exists else {}
        latest_timestamp = latest_data.get("device_timestamp")
        update_latest = (
            latest_timestamp is None or recorded_at > _utc(latest_timestamp)
        )
        transaction.create(event_ref, location_data)
        transaction.set(
            status_ref,
            {
                "device_id": payload.device_id,
                "tenant_id": tenant_id,
                "connectivity_status": "online",
                "battery_level": payload.battery_level,
                "last_seen_at": now,
                "last_location": {
                    "latitude": payload.latitude,
                    "longitude": payload.longitude,
                    "accuracy_meters": payload.accuracy_meters,
                    "device_timestamp": recorded_at,
                },
                "tamper_status": device.get("tamper_status", "unknown"),
                "updated_at": now,
            },
        )
        transaction.update(
            device_ref,
            {
                "battery_level": payload.battery_level,
                "last_seen_at": now,
                "updated_at": now,
            },
        )
        if update_latest:
            transaction.set(
                latest_ref,
                {
                    **location_data,
                    "device_id": payload.device_id,
                },
            )
            transaction.update(
                device_ref,
                {
                    "last_location": {
                        "latitude": payload.latitude,
                        "longitude": payload.longitude,
                        "accuracy_meters": payload.accuracy_meters,
                        "device_timestamp": recorded_at,
                    },
                    "updated_at": now,
                },
            )
        return {
            "accepted": True,
            "duplicate": False,
            "updated_latest": update_latest,
            "event_id": payload.event_id,
        }

    result = persist(transaction)
    if not result["duplicate"] and result["updated_latest"]:
        process_geofence_transitions(
            database=database,
            payload=payload,
            tenant_id=tenant_id,
            recorded_at=recorded_at,
            received_at=now,
            actor_uid=actor_uid,
        )
    return result


def process_geofence_transitions(
    database: Any,
    payload: LocationIngest,
    tenant_id: str,
    recorded_at: datetime,
    received_at: datetime,
    actor_uid: str,
) -> None:
    geofences = (
        database.collection("geofences")
        .where("tenant_id", "==", tenant_id)
        .where("enabled", "==", True)
        .stream()
    )
    for geofence_snapshot in geofences:
        geofence = geofence_snapshot.to_dict() or {}
        shape_type = geofence.get("shape_type", "circle")
        if shape_type == "polygon":
            coordinates = geofence.get("polygon_coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 4:
                continue
            inside, boundary_distance = polygon_relation(
                payload.latitude, payload.longitude, coordinates
            )
            distance_to_boundary = boundary_distance
        else:
            try:
                distance = haversine_meters(
                    payload.latitude,
                    payload.longitude,
                    float(geofence["center_latitude"]),
                    float(geofence["center_longitude"]),
                )
                radius = float(geofence["radius_meters"])
            except (KeyError, TypeError, ValueError):
                continue
            distance_to_boundary = abs(distance - radius)
            inside = distance < radius
        # Locations too imprecise to establish a boundary crossing are ignored.
        if distance_to_boundary <= payload.accuracy_meters:
            continue
        state_id = f"{payload.device_id}_{geofence_snapshot.id}"
        state_ref = database.collection("geofence_states").document(state_id)
        state_snapshot = state_ref.get()
        previous = state_snapshot.to_dict() if state_snapshot.exists else None
        prior_inside = previous.get("inside") if previous else None
        if prior_inside is None:
            state_ref.set(
                {
                    "tenant_id": tenant_id,
                    "device_id": payload.device_id,
                    "geofence_id": geofence_snapshot.id,
                    "inside": inside,
                    "updated_at": received_at,
                }
            )
            continue
        if prior_inside == inside:
            continue

        alert_type = "geofence_entry" if inside else "geofence_exit"
        alert_id = f"{payload.event_id}_{geofence_snapshot.id}_{alert_type}"
        alert_ref = database.collection("alerts").document(alert_id)
        alert_ref.set(
            {
                "alert_id": alert_id,
                "tenant_id": tenant_id,
                "device_id": payload.device_id,
                "alert_type": alert_type,
                "severity": "high",
                "description": (
                    f"Device crossed the boundary of geofence {geofence.get('name', geofence_snapshot.id)}."
                ),
                "latitude": payload.latitude,
                "longitude": payload.longitude,
                "event_timestamp": recorded_at,
                "received_at": received_at,
                "status": "open",
                "created_by": actor_uid,
            },
            merge=True,
        )
        record_mock_notification(database, tenant_id, alert_id, alert_type)
        database.collection("audit_logs").document(str(uuid4())).create(
            {
                "tenant_id": tenant_id,
                "actor_uid": actor_uid,
                "action": f"alert.create.{alert_type}",
                "resource_type": "alert",
                "resource_id": alert_id,
                "timestamp": received_at,
                "result": "success",
            }
        )
        state_ref.set(
            {
                "tenant_id": tenant_id,
                "device_id": payload.device_id,
                "geofence_id": geofence_snapshot.id,
                "inside": inside,
                "updated_at": received_at,
            }
        )


