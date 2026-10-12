import pytest
from pydantic import ValidationError

from app.schemas.devices import DeviceCreate


def test_device_schema_accepts_well_formed_device_id() -> None:
    device = DeviceCreate(device_id="C05-001", tenant_id="tenant-a")

    assert device.device_id == "C05-001"
    assert device.tenant_id == "tenant-a"


def test_device_schema_rejects_path_like_device_id() -> None:
    with pytest.raises(ValidationError):
        DeviceCreate(device_id="../secrets")
