"""Notification boundary with a safe development implementation.

No SMS, email, or push provider is configured. The mock records an attempted
delivery in Firestore and makes no network calls.
"""

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from app.core.config import get_settings


class NotificationProvider(Protocol):
    def deliver(self, message: dict[str, Any]) -> dict[str, str]: ...


class MockNotificationProvider:
    def deliver(self, message: dict[str, Any]) -> dict[str, str]:
        return {"status": "mocked", "provider": "development_mock"}


def mock_notifications_enabled() -> bool:
    settings = get_settings()
    return (
        settings.notification_mode == "mock"
        and settings.environment.lower() in {"development", "test"}
    )


def record_mock_notification(
    database: Any,
    tenant_id: str,
    alert_id: str,
    alert_type: str,
) -> str | None:
    """Create a minimal delivery record without storing recipient details."""
    if not mock_notifications_enabled():
        return None
    delivery_id = str(uuid4())
    result = MockNotificationProvider().deliver(
        {"tenant_id": tenant_id, "alert_id": alert_id, "alert_type": alert_type}
    )
    database.collection("notification_deliveries").document(delivery_id).create(
        {
            "delivery_id": delivery_id,
            "tenant_id": tenant_id,
            "alert_id": alert_id,
            "channel": "mock",
            "status": result["status"],
            "provider": result["provider"],
            "created_at": datetime.now(timezone.utc),
        }
    )
    return delivery_id
