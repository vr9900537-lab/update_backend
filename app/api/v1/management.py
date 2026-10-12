from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import get_current_user
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import MANAGEMENT_ROLES, require_roles
from app.schemas.management import NotificationPreferences, TenantCreate, TenantRecord
from app.schemas.users import UserProfile, UserRole

router = APIRouter(tags=["management"])


def _database() -> Any:
    try:
        return get_firebase_client().get_database()
    except FirebaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Firestore is unavailable.") from exc


@router.post(
    "/tenants",
    response_model=TenantRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))],
)
def create_tenant(
    payload: TenantCreate,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> TenantRecord:
    now = datetime.now(timezone.utc)
    data = {**payload.model_dump(), "created_at": now, "updated_at": now}
    database = _database()
    ref = database.collection("tenants").document(payload.tenant_id)
    if ref.get().exists:
        raise HTTPException(status_code=409, detail="Tenant ID already exists.")
    batch = database.batch()
    batch.create(ref, data)
    batch.create(
        database.collection("audit_logs").document(str(uuid4())),
        {
            "tenant_id": payload.tenant_id,
            "actor_uid": actor.uid,
            "action": "tenant.create",
            "resource_type": "tenant",
            "resource_id": payload.tenant_id,
            "timestamp": now,
            "result": "success",
        },
    )
    batch.commit()
    return TenantRecord.model_validate(data)


@router.get(
    "/tenants",
    response_model=list[TenantRecord],
    dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))],
)
def list_tenants(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[TenantRecord]:
    database = _database()
    return [
        TenantRecord.model_validate({**(snapshot.to_dict() or {}), "tenant_id": snapshot.id})
        for snapshot in database.collection("tenants").limit(limit).stream()
    ]


@router.get("/notifications/preferences", response_model=NotificationPreferences)
def get_notification_preferences(
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> NotificationPreferences:
    snapshot = (
        _database().collection("notification_preferences").document(actor.uid).get()
    )
    return NotificationPreferences.model_validate(snapshot.to_dict() or {})


@router.put("/notifications/preferences", response_model=NotificationPreferences)
def put_notification_preferences(
    payload: NotificationPreferences,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> NotificationPreferences:
    data = {
        **payload.model_dump(),
        "uid": actor.uid,
        "tenant_id": actor.tenant_id,
        "updated_at": datetime.now(timezone.utc),
    }
    _database().collection("notification_preferences").document(actor.uid).set(data)
    return NotificationPreferences.model_validate(data)


@router.get(
    "/audit-logs",
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def list_audit_logs(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    database = _database()
    query = database.collection("audit_logs")
    if actor.role == UserRole.SUPER_ADMIN:
        if tenant_id:
            query = query.where("tenant_id", "==", tenant_id)
    else:
        if not actor.tenant_id or (tenant_id and tenant_id != actor.tenant_id):
            raise HTTPException(status_code=403, detail="Tenant access denied.")
        query = query.where("tenant_id", "==", actor.tenant_id)
    return [
        {**(snapshot.to_dict() or {}), "audit_id": snapshot.id}
        for snapshot in query.order_by("timestamp", direction="DESCENDING").limit(limit).stream()
    ]
