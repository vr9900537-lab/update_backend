from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from uuid import uuid4

from app.core.auth import get_current_user
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import OPERATIONS_ROLES, require_roles
from app.schemas.tracking import DeviceAlert
from app.schemas.users import UserProfile, UserRole

router = APIRouter(prefix="/alerts", tags=["alerts"])


class ResolveRequest(BaseModel):
    resolution_notes: str = Field(min_length=1, max_length=2000)


def _database() -> Any:
    try:
        return get_firebase_client().get_database()
    except FirebaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Firestore is unavailable.") from exc


def _alert(alert_id: str, actor: UserProfile) -> tuple[Any, dict[str, Any]]:
    ref = _database().collection("alerts").document(alert_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Alert not found.")
    data = snapshot.to_dict() or {}
    if actor.role != UserRole.SUPER_ADMIN and data.get("tenant_id") != actor.tenant_id:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return ref, data


def _audit(actor: UserProfile, tenant_id: str, action: str, alert_id: str) -> None:
    _database().collection("audit_logs").document(str(uuid4())).create(
        {
            "tenant_id": tenant_id,
            "actor_uid": actor.uid,
            "action": action,
            "resource_type": "alert",
            "resource_id": alert_id,
            "timestamp": datetime.now(timezone.utc),
            "result": "success",
        }
    )


@router.get("", response_model=list[DeviceAlert])
def list_alerts(
    actor: Annotated[UserProfile, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    alert_status: str | None = Query(default=None, alias="status", max_length=32),
) -> list[DeviceAlert]:
    query = _database().collection("alerts")
    if actor.role != UserRole.SUPER_ADMIN:
        if not actor.tenant_id:
            raise HTTPException(status_code=403, detail="Your account is not assigned to a tenant.")
        query = query.where("tenant_id", "==", actor.tenant_id)
    if alert_status:
        query = query.where("status", "==", alert_status)
    result: list[DeviceAlert] = []
    for snapshot in query.limit(limit).stream():
        try:
            result.append(
                DeviceAlert.model_validate(
                    {**(snapshot.to_dict() or {}), "alert_id": snapshot.id}
                )
            )
        except ValidationError as exc:
            raise HTTPException(status_code=500, detail="Stored alert is invalid.") from exc
    return result


@router.get("/{alert_id}", response_model=DeviceAlert)
def get_alert(
    alert_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceAlert:
    _, data = _alert(alert_id, actor)
    return DeviceAlert.model_validate({**data, "alert_id": alert_id})


@router.post(
    "/{alert_id}/acknowledge",
    response_model=DeviceAlert,
    dependencies=[Depends(require_roles(*OPERATIONS_ROLES))],
)
def acknowledge_alert(
    alert_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceAlert:
    ref, data = _alert(alert_id, actor)
    if data.get("status") == "resolved":
        raise HTTPException(status_code=409, detail="Resolved alerts cannot be acknowledged.")
    now = datetime.now(timezone.utc)
    updates = {
        "status": "acknowledged",
        "acknowledged_by": actor.uid,
        "acknowledged_at": now,
    }
    ref.update(updates)
    data.update(updates)
    _audit(actor, data["tenant_id"], "alert.acknowledge", alert_id)
    return DeviceAlert.model_validate({**data, "alert_id": alert_id})


@router.post(
    "/{alert_id}/resolve",
    response_model=DeviceAlert,
    dependencies=[Depends(require_roles(*OPERATIONS_ROLES))],
)
def resolve_alert(
    alert_id: str,
    payload: ResolveRequest,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> DeviceAlert:
    ref, data = _alert(alert_id, actor)
    if data.get("status") == "resolved":
        raise HTTPException(status_code=409, detail="Alert is already resolved.")
    updates = {
        "status": "resolved",
        "resolution_notes": payload.resolution_notes,
        "resolved_by": actor.uid,
        "resolved_at": datetime.now(timezone.utc),
    }
    ref.update(updates)
    data.update(updates)
    _audit(actor, data["tenant_id"], "alert.resolve", alert_id)
    return DeviceAlert.model_validate({**data, "alert_id": alert_id})
