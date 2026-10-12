from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import get_current_user
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import MANAGEMENT_ROLES, require_roles
from app.schemas.management import PersonCreate, PersonRecord
from app.schemas.users import UserProfile, UserRole

router = APIRouter(prefix="/persons", tags=["persons"])


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


@router.post("", response_model=PersonRecord, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))])
def create_person(
    payload: PersonCreate,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> PersonRecord:
    tenant_id = _tenant(actor, payload.tenant_id)
    person_id = str(uuid4())
    now = datetime.now(timezone.utc)
    data = {
        "tenant_id": tenant_id,
        "reference_number": payload.reference_number,
        "display_alias": payload.display_alias,
        "assigned_device_id": None,
        "monitoring_status": payload.monitoring_status,
        "assignment_start": None,
        "assignment_end": None,
        "created_at": now,
        "updated_at": now,
    }
    database = _database()
    if not database.collection("tenants").document(tenant_id).get().exists:
        raise HTTPException(status_code=422, detail="Tenant does not exist.")
    database.collection("persons").document(person_id).create(data)
    database.collection("audit_logs").document(str(uuid4())).create(
        {
            "tenant_id": tenant_id,
            "actor_uid": actor.uid,
            "action": "person.create",
            "resource_type": "person",
            "resource_id": person_id,
            "timestamp": now,
            "result": "success",
        }
    )
    return PersonRecord.model_validate({**data, "person_id": person_id})


@router.get("", response_model=list[PersonRecord])
def list_persons(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    tenant_id: str | None = None,
) -> list[PersonRecord]:
    database = _database()
    query = database.collection("persons")
    if actor.role == UserRole.SUPER_ADMIN:
        if tenant_id:
            query = query.where("tenant_id", "==", tenant_id)
    else:
        query = query.where("tenant_id", "==", _tenant(actor, tenant_id))
    return [
        PersonRecord.model_validate({**(snapshot.to_dict() or {}), "person_id": snapshot.id})
        for snapshot in query.limit(limit).stream()
    ]
