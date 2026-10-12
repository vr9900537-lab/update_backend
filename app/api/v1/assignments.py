from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.devices import _audit, _database, _load_device
from app.core.auth import get_current_user
from app.core.permissions import MANAGEMENT_ROLES, require_roles
from app.schemas.devices import AssignmentRequest, AssignmentResponse
from app.schemas.users import UserProfile

router = APIRouter(prefix="/devices", tags=["assignments"])


@router.post(
    "/{device_id}/assign",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def assign_device(
    device_id: str,
    payload: AssignmentRequest,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> AssignmentResponse:
    database = _database()
    device_ref, device = _load_device(device_id, actor)
    tenant_id = device["tenant_id"]
    if device.get("assigned_person_id"):
        raise HTTPException(status_code=409, detail="Device is already assigned.")

    person_ref = database.collection("persons").document(payload.person_id)
    person_snapshot = person_ref.get()
    if not person_snapshot.exists:
        raise HTTPException(status_code=404, detail="Person not found.")
    person = person_snapshot.to_dict() or {}
    if person.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Person not found.")
    if person.get("monitoring_status") != "active":
        raise HTTPException(status_code=409, detail="Person is not actively monitored.")
    if person.get("assigned_device_id"):
        raise HTTPException(status_code=409, detail="Person already has an assigned device.")

    now = datetime.now(timezone.utc)
    assignment_id = str(uuid4())
    assignment_ref = database.collection("device_assignments").document(assignment_id)
    batch = database.batch()
    batch.create(
        assignment_ref,
        {
            "assignment_id": assignment_id,
            "tenant_id": tenant_id,
            "device_id": device_id,
            "person_id": payload.person_id,
            "assigned_by": actor.uid,
            "assigned_at": now,
            "unassigned_at": None,
            "status": "active",
        },
    )
    batch.update(
        device_ref,
        {"assigned_person_id": payload.person_id, "assigned_at": now, "updated_at": now},
    )
    batch.update(
        person_ref,
        {"assigned_device_id": device_id, "assignment_start": now, "updated_at": now},
    )
    batch.commit()
    _audit(database, actor, tenant_id, "device.assign", device_id)
    return AssignmentResponse(
        assignment_id=assignment_id,
        device_id=device_id,
        person_id=payload.person_id,
        status="active",
        assigned_at=now,
    )


@router.post(
    "/{device_id}/unassign",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))],
)
def unassign_device(
    device_id: str,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> None:
    database = _database()
    device_ref, device = _load_device(device_id, actor)
    person_id = device.get("assigned_person_id")
    if not person_id:
        raise HTTPException(status_code=409, detail="Device is not assigned.")
    now = datetime.now(timezone.utc)
    active_assignments = (
        database.collection("device_assignments")
        .where("device_id", "==", device_id)
        .where("status", "==", "active")
        .limit(1)
        .stream()
    )
    assignment = next(iter(active_assignments), None)
    if assignment is None:
        raise HTTPException(
            status_code=409,
            detail="Active assignment history is missing; contact an administrator.",
        )

    person_ref = database.collection("persons").document(person_id)
    batch = database.batch()
    batch.update(assignment.reference, {"status": "unassigned", "unassigned_at": now})
    batch.update(
        device_ref,
        {"assigned_person_id": None, "assigned_at": None, "updated_at": now},
    )
    batch.update(
        person_ref,
        {"assigned_device_id": None, "assignment_end": now, "updated_at": now},
    )
    batch.commit()
    _audit(database, actor, device["tenant_id"], "device.unassign", device_id)
