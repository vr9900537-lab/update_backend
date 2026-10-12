import pytest
from pydantic import ValidationError

from app.schemas.management import DeviceConfiguration, NotificationPreferences
from app.services.notifications import MockNotificationProvider


def test_device_configuration_rejects_unverified_fields() -> None:
    with pytest.raises(ValidationError):
        DeviceConfiguration.model_validate({"command_encoding": "not-supported"})


def test_notification_preferences_accept_supported_alert_types() -> None:
    preferences = NotificationPreferences(
        push_enabled=True,
        alert_types=["sos", "offline_device"],
    )

    assert preferences.alert_types == ["sos", "offline_device"]


def test_notification_preferences_reject_unknown_alert_types() -> None:
    with pytest.raises(ValidationError):
        NotificationPreferences(alert_types=["made_up_event"])


def test_mock_notification_provider_never_claims_real_delivery() -> None:
    result = MockNotificationProvider().deliver({"alert_id": "alert-1"})

    assert result == {"status": "mocked", "provider": "development_mock"}
