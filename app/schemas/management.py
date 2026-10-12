from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.users import UserRole, UserStatus


class UserRoleUpdate(BaseModel):
    role: UserRole
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: UserStatus = UserStatus.ACTIVE


class DeviceGroupCreate(BaseModel):
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    device_ids: list[str] = Field(default_factory=list, max_length=200)


class DeviceGroupPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    device_ids: list[str] | None = Field(default=None, max_length=200)


class DeviceGroupRecord(BaseModel):
    group_id: str
    tenant_id: str
    name: str
    description: str | None = None
    device_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class NotificationPreferences(BaseModel):
    email_enabled: bool = False
    sms_enabled: bool = False
    push_enabled: bool = False
    alert_types: list[Literal[
        "sos", "geofence_entry", "geofence_exit", "low_battery",
        "tamper", "offline_device", "communication_failure",
    ]] = Field(default_factory=list, max_length=20)


class DeviceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_interval_seconds: int | None = Field(default=None, ge=5, le=86_400)
    low_battery_threshold: int | None = Field(default=None, ge=1, le=50)
    location_accuracy_threshold_meters: int | None = Field(default=None, ge=1, le=10_000)


class TenantCreate(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=160)
    status: Literal["active", "inactive"] = "active"


class TenantRecord(TenantCreate):
    created_at: datetime
    updated_at: datetime


class PersonCreate(BaseModel):
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    reference_number: str = Field(min_length=1, max_length=128)
    display_alias: str = Field(min_length=1, max_length=120)
    monitoring_status: Literal["active", "inactive", "released"] = "active"


class PersonRecord(BaseModel):
    person_id: str
    tenant_id: str
    reference_number: str
    display_alias: str
    assigned_device_id: str | None = None
    monitoring_status: Literal["active", "inactive", "released"]
    assignment_start: datetime | None = None
    assignment_end: datetime | None = None
    created_at: datetime
    updated_at: datetime
