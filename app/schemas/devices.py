from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DeviceState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEACTIVATED = "deactivated"
    UNKNOWN = "unknown"


class DeviceCreate(BaseModel):
    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    vendor_device_id: str | None = Field(default=None, max_length=128)
    imei: str | None = Field(default=None, max_length=32)
    serial_number: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    firmware_version: str | None = Field(default=None, max_length=128)
    device_type: str = Field(default="custody_band", max_length=64)


class DevicePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, max_length=128)
    firmware_version: str | None = Field(default=None, max_length=128)
    device_type: str | None = Field(default=None, max_length=64)
    status: DeviceState | None = None


class DeviceRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_id: str
    tenant_id: str
    vendor_device_id: str | None = None
    imei: str | None = None
    serial_number: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    device_type: str
    status: DeviceState
    assigned_person_id: str | None = None
    battery_level: int | None = Field(default=None, ge=0, le=100)
    last_seen_at: datetime | None = None
    last_location: dict[str, float] | None = None
    tamper_status: str = "unknown"
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class AssignmentRequest(BaseModel):
    person_id: str = Field(min_length=1, max_length=128)


class AssignmentResponse(BaseModel):
    assignment_id: str
    device_id: str
    person_id: str
    status: str
    assigned_at: datetime


class DeviceStatusResponse(BaseModel):
    device_id: str
    connectivity_status: str
    battery_level: int | None = None
    last_seen_at: datetime | None = None
    last_location: dict[str, float] | None = None
    tamper_status: str = "unknown"
