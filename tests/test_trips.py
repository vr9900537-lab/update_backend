from datetime import datetime, timedelta, timezone

from app.services.trip_service import build_trips


def test_trip_builder_segments_idle_gaps_and_uses_device_time() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = [
        {"event_id": "a", "device_timestamp": start, "latitude": 0.0, "longitude": 0.0},
        {
            "event_id": "b",
            "device_timestamp": start + timedelta(minutes=2),
            "latitude": 0.0,
            "longitude": 0.002,
        },
        {
            "event_id": "c",
            "device_timestamp": start + timedelta(hours=1),
            "latitude": 1.0,
            "longitude": 1.0,
        },
        {
            "event_id": "d",
            "device_timestamp": start + timedelta(hours=1, minutes=2),
            "latitude": 1.0,
            "longitude": 1.002,
        },
    ]

    trips = build_trips("device-1", "tenant-1", points, 1800, 100)

    assert len(trips) == 2
    assert trips[0]["started_at"] == start
    assert trips[0]["ended_at"] == start + timedelta(minutes=2)
    assert trips[0]["distance_meters"] > 100
