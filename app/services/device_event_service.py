from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from firebase_admin import firestore
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.schemas.tracking import SimulatedDeviceEvent
from app.services.notifications import mock_notifications_enabled


def ingest_simulated_event(
    database: Any,
    payload: SimulatedDeviceEvent,
    tenant_id: str,
    actor_uid: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    recorded_at = payload.device_timestamp
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    else:
        recorded_at = recorded_at.astimezone(timezone.utc)
    if recorded_at > now + timedelta(minutes=5):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Device timestamp is too far in the future.",
        )

    device_ref = database.collection("devices").document(payload.device_id)
    device_snapshot = device_ref.get()
    device = device_snapshot.to_dict() if device_snapshot.exists else None
    if (
        not isinstance(device, dict)
        or device.get("tenant_id") != tenant_id
        or device.get("status") != "active"
        or device.get("deleted_at") is not None
    ):
        raise HTTPException(status_code=404, detail="Device not found.")

    battery_threshold = int(
        (device.get("configuration") or {}).get("low_battery_threshold")
        or get_settings().low_battery_threshold
    )
    alert_type: str | None = None
    alert_description: str | None = None
    if payload.event_type == "sos" and payload.sos_active:
        alert_type, alert_description = "sos", "SOS signal received from device."
    elif payload.event_type == "tamper" and payload.tamper_state == "triggered":
        alert_type, alert_description = "tamper", "Tamper signal received from device."
    elif (
        payload.event_type in {"battery", "heartbeat"}
        and payload.battery_level is not None
        and payload.battery_level <= battery_threshold
    ):
        alert_type, alert_description = "low_battery", "Battery is below the configured threshold."

    event_doc_id = sha256(
        f"{payload.device_id}\0{payload.event_id}".encode("utf-8")
    ).hexdigest()
    event_ref = database.collection("device_events").document(event_doc_id)
    status_ref = database.collection("device_status").document(payload.device_id)
    alert_id = f"{event_doc_id}_{alert_type}" if alert_type else None
    alert_ref = database.collection("alerts").document(alert_id) if alert_id else None
    delivery_ref = (
        database.collection("notification_deliveries").document(str(uuid4()))
        if alert_id and mock_notifications_enabled()
        else None
    )
    audit_ref = (
        database.collection("audit_logs").document(str(uuid4()))
        if alert_id
        else None
    )
    event_data = {
        "event_id": payload.event_id,
        "tenant_id": tenant_id,
        "device_id": payload.device_id,
        "event_type": payload.event_type,
        "payload": payload.model_dump(
            exclude={
                "device_id",
                "event_id",
                "event_type",
                "device_timestamp",
                "source",
            }
        ),
        "device_timestamp": recorded_at,
        "received_at": now,
        "source": "simulated",
        "processing_status": "processed",
    }
    transaction = database.transaction()

    @firestore.transactional
    def persist(transaction: Any) -> dict[str, Any]:
        existing = event_ref.get(transaction=transaction)
        if existing.exists:
            return {"accepted": True, "duplicate": True, "alert_id": alert_id}
        prior_status = status_ref.get(transaction=transaction)
        prior_data = prior_status.to_dict() if prior_status.exists else {}
        prior_event_timestamp = (prior_data or {}).get("last_event_device_timestamp")
        state_is_newer = (
            prior_event_timestamp is None
            or recorded_at >= prior_event_timestamp
        )
        transaction.create(event_ref, event_data)
        status_updates = {
            "tenant_id": tenant_id,
            "device_id": payload.device_id,
            "connectivity_status": "online",
            "last_seen_at": now,
            "updated_at": now,
        }
        if state_is_newer:
            status_updates["last_event_device_timestamp"] = recorded_at
            if payload.battery_level is not None:
                status_updates["battery_level"] = payload.battery_level
            if payload.event_type == "tamper":
                status_updates["tamper_status"] = payload.tamper_state
        transaction.set(status_ref, status_updates, merge=True)
        device_updates: dict[str, Any] = {"last_seen_at": now, "updated_at": now}
        if state_is_newer and payload.battery_level is not None:
            device_updates["battery_level"] = payload.battery_level
        transaction.update(device_ref, device_updates)
        if alert_ref is not None and alert_id is not None:
            transaction.create(
                alert_ref,
                {
                    "alert_id": alert_id,
                    "tenant_id": tenant_id,
                    "device_id": payload.device_id,
                    "alert_type": alert_type,
                    "severity": "critical" if alert_type == "sos" else "high",
                    "description": alert_description,
                    "event_timestamp": recorded_at,
                    "received_at": now,
                    "status": "open",
                    "created_by": actor_uid,
                },
            )
            if delivery_ref is not None:
                transaction.create(
                    delivery_ref,
                    {
                        "tenant_id": tenant_id,
                        "alert_id": alert_id,
                        "channel": "mock",
                        "provider": "development_mock",
                        "status": "mocked",
                        "created_at": now,
                    },
                )
            transaction.create(
                audit_ref,
                {
                    "tenant_id": tenant_id,
                    "actor_uid": actor_uid,
                    "action": f"alert.create.{alert_type}",
                    "resource_type": "alert",
                    "resource_id": alert_id,
                    "timestamp": now,
                    "result": "success",
                },
            )
        return {"accepted": True, "duplicate": False, "alert_id": alert_id}

    return persist(transaction)
