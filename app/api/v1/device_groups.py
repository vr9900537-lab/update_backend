from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError

from app.core.auth import get_current_user
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import MANAGEMENT_ROLES, require_roles
from app.schemas.management import DeviceGroupCreate, DeviceGroupPatch, DeviceGroupRecord
from app.schemas.users import UserProfile, UserRole

router = APIRouter(prefix="/device-groups", tags=["device groups"])


def _database() -> Any:
    try:
        return get_firebase_client().get_database()
    except FirebaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Firestore is unavailable.") from exc


def _tenant(actor: UserProfile, requested: str | None = None) -> str:
    if actor.role == UserRole.SUPER_ADMIN:
        if not requested:
            raise HTTPException(status_code=422, detail="tenant_id is required.")
        return requested
    if not actor.tenant_id or (requested and requested != actor.tenant_id):
        raise HTTPException(status_code=403, detail="Tenant access denied.")
    return actor.tenant_id


def _validate_devices(database: Any, tenant_id: str, device_ids: list[str]) -> None:
    if len(device_ids) != len(set(device_ids)):
        raise HTTPException(status_code=422, detail="device_ids must be unique.")
    for device_id in device_ids:
        snapshot = database.collection("devices").document(device_id).get()
        device = snapshot.to_dict() if snapshot.exists else None
        if not isinstance(device, dict) or device.get("tenant_id") != tenant_id or device.get("deleted_at"):
            raise HTTPException(status_code=404, detail="A device was not found in this tenant.")


def _record(data: dict[str, Any], group_id: str) -> DeviceGroupRecord:
    try:
        return DeviceGroupRecord.model_validate({**data, "group_id": group_id})
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail="Stored device group is invalid.") from exc


def _audit(database: Any, actor: UserProfile, tenant_id: str, action: str, group_id: str) -> None:
    database.collection("audit_logs").document(str(uuid4())).create(
        {
            "tenant_id": tenant_id,
            "actor_uid": actor.uid,
            "action": action,
            "resource_type": "device_group",
            "resource_id": group_id,
            "timestamp": datetime.now(timezone.utc),
            "result": "success",
        }
    )


@router.post("", response_model=DeviceGroupRecord, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))])
def create_device_group(
    payload: DeviceGroupCreate,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceGroupRecord:
    database = _database()
    tenant_id = _tenant(actor, payload.tenant_id)
    if not database.collection("tenants").document(tenant_id).get().exists:
        raise HTTPException(status_code=422, detail="Tenant does not exist.")
    _validate_devices(database, tenant_id, payload.device_ids)
    now = datetime.now(timezone.utc)
    group_id = str(uuid4())
    data = {**payload.model_dump(exclude={"tenant_id"}), "tenant_id": tenant_id,
            "created_at": now, "updated_at": now}
    database.collection("device_groups").document(group_id).create(data)
    _audit(database, actor, tenant_id, "device_group.create", group_id)
    return _record(data, group_id)


@router.get("", response_model=list[DeviceGroupRecord])
def list_device_groups(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    tenant_id: str | None = None,
) -> list[DeviceGroupRecord]:
    database = _database()
    query = database.collection("device_groups")
    if actor.role == UserRole.SUPER_ADMIN:
        if tenant_id:
            query = query.where("tenant_id", "==", tenant_id)
    else:
        query = query.where("tenant_id", "==", _tenant(actor, tenant_id))
    return [_record(snapshot.to_dict() or {}, snapshot.id) for snapshot in query.limit(limit).stream()]


@router.patch("/{group_id}", response_model=DeviceGroupRecord,
              dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))])
def update_device_group(
    group_id: str,
    payload: DeviceGroupPatch,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceGroupRecord:
    database = _database()
    ref = database.collection("device_groups").document(group_id)
    snapshot = ref.get()
    data = snapshot.to_dict() if snapshot.exists else None
    if not isinstance(data, dict) or (actor.role != UserRole.SUPER_ADMIN and data.get("tenant_id") != actor.tenant_id):
        raise HTTPException(status_code=404, detail="Device group not found.")
    updates = payload.model_dump(exclude_unset=True)
    if "device_ids" in updates:
        _validate_devices(database, data["tenant_id"], updates["device_ids"] or [])
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        ref.update(updates)
        data.update(updates)
        _audit(database, actor, data["tenant_id"], "device_group.update", group_id)
    return _record(data, group_id)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))])
def delete_device_group(
    group_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> None:
    database = _database()
    ref = database.collection("device_groups").document(group_id)
    snapshot = ref.get()
    data = snapshot.to_dict() if snapshot.exists else None
    if not isinstance(data, dict) or (actor.role != UserRole.SUPER_ADMIN and data.get("tenant_id") != actor.tenant_id):
        raise HTTPException(status_code=404, detail="Device group not found.")
    ref.delete()
    _audit(database, actor, data["tenant_id"], "device_group.delete", group_id)
