from datetime import datetime, timezone

from app.schemas.tracking import DeviceAlert


def test_alert_response_contains_status_and_event_time() -> None:
    alert = DeviceAlert(
        alert_id="alert-1",
        tenant_id="tenant-a",
        device_id="device-1",
        alert_type="geofence_entry",
        severity="high",
        description="Boundary entered",
        event_timestamp=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        status="open",
    )

    assert alert.status == "open"
    assert alert.acknowledged_by is None
