from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError

from app.core.auth import get_current_user
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import MANAGEMENT_ROLES, require_roles
from app.schemas.geofences import GeofenceCreate, GeofencePatch, GeofenceRecord
from app.schemas.users import UserProfile, UserRole

router = APIRouter(prefix="/geofences", tags=["geofences"])


def _database() -> Any:
    try:
        return get_firebase_client().get_database()
    except FirebaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Firestore is unavailable.") from exc


def _tenant(user: UserProfile, tenant_id: str | None = None) -> str:
    if user.role == UserRole.SUPER_ADMIN:
        if not tenant_id:
            raise HTTPException(status_code=422, detail="tenant_id is required.")
        return tenant_id
    if not user.tenant_id or (tenant_id and tenant_id != user.tenant_id):
        raise HTTPException(status_code=403, detail="Tenant access denied.")
    return user.tenant_id


def _audit(database: Any, actor: UserProfile, tenant_id: str, action: str, geofence_id: str) -> None:
    database.collection("audit_logs").document(str(uuid4())).create(
        {
            "tenant_id": tenant_id,
            "actor_uid": actor.uid,
            "action": action,
            "resource_type": "geofence",
            "resource_id": geofence_id,
            "timestamp": datetime.now(timezone.utc),
            "result": "success",
        }
    )


@router.post(
    "",
    response_model=GeofenceRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def create_geofence(
    payload: GeofenceCreate,
    actor: Annotated[UserProfile, Depends(get_current_user)],
    tenant_id: str | None = None,
) -> GeofenceRecord:
    database = _database()
    tenant = _tenant(actor, tenant_id)
    if not database.collection("tenants").document(tenant).get().exists:
        raise HTTPException(status_code=422, detail="Tenant does not exist.")
    now = datetime.now(timezone.utc)
    geofence_id = str(uuid4())
    data = {
        **payload.model_dump(),
        "geofence_id": geofence_id,
        "tenant_id": tenant,
        "created_by": actor.uid,
        "created_at": now,
        "updated_at": now,
    }
    database.collection("geofences").document(geofence_id).create(data)
    _audit(database, actor, tenant, "geofence.create", geofence_id)
    return GeofenceRecord.model_validate(data)


@router.get("", response_model=list[GeofenceRecord])
def list_geofences(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[GeofenceRecord]:
    query = _database().collection("geofences")
    if actor.role != UserRole.SUPER_ADMIN:
        tenant = _tenant(actor)
        query = query.where("tenant_id", "==", tenant)
    result: list[GeofenceRecord] = []
    for snapshot in query.limit(limit).stream():
        data = snapshot.to_dict() or {}
        try:
            result.append(
                GeofenceRecord.model_validate(
                    {**data, "geofence_id": snapshot.id}
                )
            )
        except ValidationError as exc:
            raise HTTPException(status_code=500, detail="Stored geofence is invalid.") from exc
    return result


@router.patch(
    "/{geofence_id}",
    response_model=GeofenceRecord,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def update_geofence(
    geofence_id: str,
    payload: GeofencePatch,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> GeofenceRecord:
    database = _database()
    ref = database.collection("geofences").document(geofence_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Geofence not found.")
    data = snapshot.to_dict() or {}
    if actor.role != UserRole.SUPER_ADMIN and data.get("tenant_id") != actor.tenant_id:
        raise HTTPException(status_code=404, detail="Geofence not found.")
    changes = payload.model_dump(exclude_unset=True)
    if changes:
        # Validate the complete resulting shape. Validating only the patch would
        # allow a partial update to leave a circle without its radius or a
        # polygon without a closed, valid ring.
        shape_fields = {
            "name",
            "shape_type",
            "center_latitude",
            "center_longitude",
            "radius_meters",
            "polygon_coordinates",
            "enabled",
        }
        resulting_shape = {
            key: data[key]
            for key in shape_fields
            if key in data
        }
        resulting_shape.update(changes)
        try:
            validated_shape = GeofenceCreate.model_validate(resulting_shape)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail="The update would leave the geofence shape invalid.",
            ) from exc
        changes = validated_shape.model_dump()
        changes["updated_at"] = datetime.now(timezone.utc)
        ref.update(changes)
        data.update(changes)
        _audit(database, actor, data["tenant_id"], "geofence.update", geofence_id)
    return GeofenceRecord.model_validate({**data, "geofence_id": geofence_id})
