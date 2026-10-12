from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.tracking import LocationIngest, SimulatedDeviceEvent


def test_location_payload_accepts_valid_coordinates() -> None:
    payload = LocationIngest(
        device_id="C05-001",
        event_id="event-1",
        latitude=17.385,
        longitude=78.4867,
        accuracy_meters=10,
        device_timestamp=datetime.now(timezone.utc),
    )

    assert payload.source == "simulated"


def test_location_payload_rejects_out_of_range_latitude() -> None:
    with pytest.raises(ValidationError):
        LocationIngest(
            device_id="C05-001",
            event_id="event-2",
            latitude=91,
            longitude=78,
            accuracy_meters=10,
            device_timestamp=datetime.now(timezone.utc),
        )


def test_sos_event_requires_explicit_signal() -> None:
    with pytest.raises(ValidationError):
        SimulatedDeviceEvent(
            device_id="C05-001",
            event_id="event-sos",
            event_type="sos",
            device_timestamp=datetime.now(timezone.utc),
        )


def test_low_battery_event_requires_valid_level() -> None:
    event = SimulatedDeviceEvent(
        device_id="C05-001",
        event_id="event-battery",
        event_type="battery",
        battery_level=10,
        device_timestamp=datetime.now(timezone.utc),
    )

    assert event.source == "simulated"
