from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.services.notifications import mock_notifications_enabled

logger = logging.getLogger(__name__)


def mark_offline_devices(
    database: Any,
    timeout_seconds: int,
    events: list[dict[str, Any]] | None = None,
) -> int:
    """Mark online devices offline when their last heartbeat exceeded timeout."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    stale_statuses = list(
        database.collection("device_status")
        .where("connectivity_status", "==", "online")
        .where("last_seen_at", "<=", cutoff)
        # Four writes per stale device (status, alert, mock delivery, audit) fit in
        # Firestore's 500-operation batch limit.
        .limit(125)
        .stream()
    )
    if not stale_statuses:
        return 0
    batch = database.batch()
    count = 0
    now = datetime.now(timezone.utc)
    for snapshot in stale_statuses:
        data = snapshot.to_dict() or {}
        tenant_id = data.get("tenant_id")
        device_id = data.get("device_id", snapshot.id)
        last_seen_at = data.get("last_seen_at")
        batch.update(
            snapshot.reference,
            {"connectivity_status": "offline", "updated_at": now},
        )
        if isinstance(tenant_id, str) and last_seen_at is not None:
            timestamp_key = last_seen_at.strftime("%Y%m%dT%H%M%S%fZ")
            alert_id = f"offline_{device_id}_{timestamp_key}"
            batch.create(
                database.collection("alerts").document(alert_id),
                {
                    "alert_id": alert_id,
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "alert_type": "offline_device",
                    "severity": "medium",
                    "description": "Device heartbeat is older than the configured timeout.",
                    "event_timestamp": last_seen_at,
                    "received_at": now,
                    "status": "open",
                    "created_by": "offline_device_worker",
                },
            )
            batch.create(
                database.collection("audit_logs").document(str(uuid4())),
                {
                    "tenant_id": tenant_id,
                    "actor_uid": "offline_device_worker",
                    "action": "alert.create.offline_device",
                    "resource_type": "alert",
                    "resource_id": alert_id,
                    "timestamp": now,
                    "result": "success",
                },
            )
            if events is not None:
                events.append(
                    {
                        "tenant_id": tenant_id,
                        "type": "device.offline",
                        "device_id": device_id,
                        "last_seen_at": last_seen_at.isoformat(),
                    }
                )
            if mock_notifications_enabled():
                batch.create(
                    database.collection("notification_deliveries").document(str(uuid4())),
                    {
                        "tenant_id": tenant_id,
                        "alert_id": alert_id,
                        "channel": "mock",
                        "provider": "development_mock",
                        "status": "mocked",
                        "created_at": now,
                    },
                )
        count += 1
    batch.commit()
    return count


async def run_offline_device_worker() -> None:
    """Run periodic stale-device detection until the application shuts down."""
    import asyncio

    settings = get_settings()
    while True:
        try:
            database = get_firebase_client().get_database()
            events: list[dict[str, Any]] = []
            marked = await asyncio.to_thread(
                mark_offline_devices,
                database,
                settings.device_online_timeout_seconds,
                events,
            )
            from app.websockets.manager import manager

            for event in events:
                tenant_id = event.pop("tenant_id")
                await manager.publish(tenant_id, event)
            if marked:
                logger.info("Marked %s devices offline", marked)
        except FirebaseUnavailableError:
            logger.warning("Offline-device worker skipped: Firebase is unavailable")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Offline-device scan failed")
        await asyncio.sleep(max(5, settings.offline_device_scan_interval_seconds))
