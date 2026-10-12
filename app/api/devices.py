import logging
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError

from app.core.auth import get_current_user
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import MANAGEMENT_ROLES, OPERATIONS_ROLES, require_roles
from app.schemas.devices import (
    DeviceCreate,
    DevicePatch,
    DeviceRecord,
    DeviceState,
    DeviceStatusResponse,
)
from app.schemas.management import DeviceConfiguration
from app.schemas.users import UserProfile, UserRole

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["devices"])


def _database() -> Any:
    try:
        return get_firebase_client().get_database()
    except FirebaseUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firestore is unavailable.",
        ) from exc


def _tenant_id(user: UserProfile, requested: str | None = None) -> str:
    if user.role == UserRole.SUPER_ADMIN:
        if requested is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="tenant_id is required for super-admin operations.",
            )
        return requested
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not assigned to a tenant.",
        )
    if requested is not None and requested != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot access another tenant.",
        )
    return user.tenant_id


def _load_device(device_id: str, user: UserProfile) -> tuple[Any, dict[str, Any]]:
    ref = _database().collection("devices").document(device_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Device not found.")
    data = snapshot.to_dict() or {}
    if data.get("deleted_at") is not None:
        raise HTTPException(status_code=404, detail="Device not found.")
    if user.role != UserRole.SUPER_ADMIN and data.get("tenant_id") != user.tenant_id:
        raise HTTPException(status_code=404, detail="Device not found.")
    return ref, data


def _validate_device(data: dict[str, Any], device_id: str) -> DeviceRecord:
    try:
        return DeviceRecord.model_validate({**data, "device_id": device_id})
    except ValidationError as exc:
        logger.error("Invalid Firestore device record for device id %s", device_id)
        raise HTTPException(
            status_code=500,
            detail="Stored device record is invalid.",
        ) from exc


def _audit(
    database: Any,
    actor: UserProfile,
    tenant_id: str,
    action: str,
    resource_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    database.collection("audit_logs").document(str(uuid4())).set(
        {
            "tenant_id": tenant_id,
            "actor_uid": actor.uid,
            "action": action,
            "resource_type": "device",
            "resource_id": resource_id,
            "timestamp": now,
            "result": "success",
        }
    )


@router.post(
    "",
    response_model=DeviceRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def register_device(
    payload: DeviceCreate,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceRecord:
    database = _database()
    tenant_id = _tenant_id(actor, payload.tenant_id)
    if not database.collection("tenants").document(tenant_id).get().exists:
        raise HTTPException(status_code=422, detail="Tenant does not exist.")
    ref = database.collection("devices").document(payload.device_id)
    if ref.get().exists:
        raise HTTPException(status_code=409, detail="Device ID already exists.")
    if payload.imei:
        duplicate = (
            database.collection("devices")
            .where("imei", "==", payload.imei)
            .limit(1)
            .stream()
        )
        if any(item.id != payload.device_id for item in duplicate):
            raise HTTPException(status_code=409, detail="IMEI already exists.")

    now = datetime.now(timezone.utc)
    data = {
        **payload.model_dump(exclude={"tenant_id"}),
        "tenant_id": tenant_id,
        "status": DeviceState.ACTIVE.value,
        "assigned_person_id": None,
        "battery_level": None,
        "last_seen_at": None,
        "last_location": None,
        "tamper_status": "unknown",
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    ref.create(data)
    _audit(database, actor, tenant_id, "device.register", payload.device_id)
    return _validate_device(data, payload.device_id)


@router.get("", response_model=list[DeviceRecord])
def list_devices(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[DeviceRecord]:
    database = _database()
    query = database.collection("devices")
    if actor.role != UserRole.SUPER_ADMIN:
        tenant_id = _tenant_id(actor)
        query = query.where("tenant_id", "==", tenant_id)
    records: list[DeviceRecord] = []
    for snapshot in query.limit(limit).stream():
        data = snapshot.to_dict() or {}
        if data.get("deleted_at") is None:
            records.append(_validate_device(data, snapshot.id))
    return records


@router.get("/{device_id}", response_model=DeviceRecord)
def get_device(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceRecord:
    _, data = _load_device(device_id, actor)
    return _validate_device(data, device_id)


@router.patch(
    "/{device_id}",
    response_model=DeviceRecord,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def update_device(
    device_id: str,
    payload: DevicePatch,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceRecord:
    ref, data = _load_device(device_id, actor)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _validate_device(data, device_id)
    updates["updated_at"] = datetime.now(timezone.utc)
    ref.update(updates)
    data.update(updates)
    _audit(_database(), actor, data["tenant_id"], "device.update", device_id)
    return _validate_device(data, device_id)


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def deactivate_device(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> None:
    ref, data = _load_device(device_id, actor)
    now = datetime.now(timezone.utc)
    ref.update(
        {
            "status": DeviceState.DEACTIVATED.value,
            "deleted_at": now,
            "updated_at": now,
        }
    )
    _audit(_database(), actor, data["tenant_id"], "device.deactivate", device_id)


@router.get("/{device_id}/status", response_model=DeviceStatusResponse)
def get_device_status(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceStatusResponse:
    _, data = _load_device(device_id, actor)
    last_seen_at = data.get("last_seen_at")
    if last_seen_at is None:
        connectivity = "unknown"
    else:
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - last_seen_at).total_seconds()
        connectivity = (
            "online"
            if age <= get_firebase_client().settings.device_online_timeout_seconds
            else "offline"
        )
    return DeviceStatusResponse(
        device_id=device_id,
        connectivity_status=connectivity,
        battery_level=data.get("battery_level"),
        last_seen_at=last_seen_at,
        last_location=data.get("last_location"),
        tamper_status=data.get("tamper_status", "unknown"),
    )


@router.get("/{device_id}/configuration", response_model=DeviceConfiguration)
def get_device_configuration(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceConfiguration:
    _, data = _load_device(device_id, actor)
    return DeviceConfiguration.model_validate(data.get("configuration") or {})


@router.patch(
    "/{device_id}/configuration",
    response_model=DeviceConfiguration,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def update_device_configuration(
    device_id: str,
    payload: DeviceConfiguration,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceConfiguration:
    ref, data = _load_device(device_id, actor)
    configuration = dict(data.get("configuration") or {})
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is None:
            configuration.pop(key, None)
        else:
            configuration[key] = value
    ref.update({"configuration": configuration, "updated_at": datetime.now(timezone.utc)})
    _audit(_database(), actor, data["tenant_id"], "device.configuration.update", device_id)
    return DeviceConfiguration.model_validate(configuration)


