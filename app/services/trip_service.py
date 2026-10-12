from datetime import datetime, timedelta, timezone
from typing import Any

from app.utils.geo import haversine_meters


def build_trips(
    device_id: str,
    tenant_id: str,
    points: list[dict[str, Any]],
    idle_gap_seconds: int,
    minimum_distance_meters: float,
) -> list[dict[str, Any]]:
    """Build deterministic trip documents from points ordered by device time."""
    trips: list[dict[str, Any]] = []
    segment: list[dict[str, Any]] = []
    distance = 0.0

    def finish() -> None:
        nonlocal segment, distance
        if len(segment) >= 2 and distance >= minimum_distance_meters:
            first, last = segment[0], segment[-1]
            trip_id = f"trip_{device_id}_{first['event_id']}"
            trips.append(
                {
                    "trip_id": trip_id,
                    "tenant_id": tenant_id,
                    "device_id": device_id,
                    "started_at": first["device_timestamp"],
                    "ended_at": last["device_timestamp"],
                    "start_location": {
                        "latitude": first["latitude"],
                        "longitude": first["longitude"],
                    },
                    "end_location": {
                        "latitude": last["latitude"],
                        "longitude": last["longitude"],
                    },
                    "distance_meters": round(distance, 2),
                    "status": "completed",
                    "generated_by": "bounded_history_rebuild",
                }
            )
        segment = []
        distance = 0.0

    for point in points:
        timestamp = point["device_timestamp"]
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if segment:
            previous = segment[-1]
            previous_time = previous["device_timestamp"]
            if previous_time.tzinfo is None:
                previous_time = previous_time.replace(tzinfo=timezone.utc)
            if timestamp - previous_time > timedelta(seconds=idle_gap_seconds):
                finish()
        normalized = {**point, "device_timestamp": timestamp}
        if segment:
            previous = segment[-1]
            distance += haversine_meters(
                float(previous["latitude"]),
                float(previous["longitude"]),
                float(normalized["latitude"]),
                float(normalized["longitude"]),
            )
        segment.append(normalized)
    finish()
    return trips
