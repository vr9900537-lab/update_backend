from datetime import datetime
from typing import Literal
from pydantic import model_validator

from pydantic import BaseModel, Field


class LocationIngest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    event_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float = Field(ge=0, le=10_000)
    altitude_meters: float | None = Field(default=None, ge=-1_000, le=100_000)
    speed_kmh: float | None = Field(default=None, ge=0, le=500)
    heading_degrees: float | None = Field(default=None, ge=0, lt=360)
    battery_level: int | None = Field(default=None, ge=0, le=100)
    device_timestamp: datetime
    source: Literal["simulated"] = "simulated"


class LocationRecord(LocationIngest):
    tenant_id: str
    received_at: datetime


class LocationIngestResult(BaseModel):
    accepted: bool
    duplicate: bool
    updated_latest: bool
    event_id: str


class LocationPage(BaseModel):
    items: list[LocationRecord]
    next_cursor: str | None = None


class DeviceAlert(BaseModel):
    alert_id: str
    tenant_id: str
    device_id: str
    alert_type: str
    severity: str
    description: str
    latitude: float | None = None
    longitude: float | None = None
    event_timestamp: datetime
    received_at: datetime
    status: str
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    resolution_notes: str | None = None


class TripRecord(BaseModel):
    trip_id: str
    tenant_id: str
    device_id: str
    started_at: datetime
    ended_at: datetime
    start_location: dict[str, float]
    end_location: dict[str, float]
    distance_meters: float = Field(ge=0)
    status: Literal["completed"] = "completed"


class TripRebuildResult(BaseModel):
    device_id: str
    points_processed: int
    trips_written: int
    truncated: bool


class SimulatedDeviceEvent(BaseModel):
    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    event_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    event_type: Literal["heartbeat", "battery", "sos", "tamper"]
    device_timestamp: datetime
    battery_level: int | None = Field(default=None, ge=0, le=100)
    sos_active: bool | None = None
    tamper_state: Literal["triggered", "clear"] | None = None
    source: Literal["simulated"] = "simulated"

    @model_validator(mode="after")
    def validate_event_payload(self) -> "SimulatedDeviceEvent":
        if self.event_type == "battery" and self.battery_level is None:
            raise ValueError("Battery events require battery_level")
        if self.event_type == "sos" and self.sos_active is None:
            raise ValueError("SOS events require sos_active")
        if self.event_type == "tamper" and self.tamper_state is None:
            raise ValueError("Tamper events require tamper_state")
        return self


class DeviceEventIngestResult(BaseModel):
    accepted: bool
    duplicate: bool
    alert_id: str | None = None
