from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.tracking import LocationIngest


def simulated_location(
    device_id: str,
    latitude: float,
    longitude: float,
    battery_level: int = 80,
) -> LocationIngest:
    """Create explicitly simulated test data, never a real-device assertion."""
    return LocationIngest(
        device_id=device_id,
        event_id=f"sim-{uuid4()}",
        latitude=latitude,
        longitude=longitude,
        accuracy_meters=25,
        battery_level=battery_level,
        device_timestamp=datetime.now(timezone.utc),
        source="simulated",
    )
