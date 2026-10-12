import logging
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError

from app.core.auth import get_current_user
from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import require_roles
from app.schemas.users import UserProfile, UserRole, UserStatus
from app.schemas.management import UserRoleUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfile)
def get_my_profile(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    return current_user


@router.get(
    "",
    response_model=list[UserProfile],
    dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))],
)
def list_user_profiles(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[UserProfile]:
    try:
        documents = (
            get_firebase_client()
            .get_database()
            .collection("users")
            .limit(limit)
            .stream()
        )
        profiles: list[UserProfile] = []
        for document in documents:
            data: Any = document.to_dict()
            if not isinstance(data, dict):
                continue
            try:
                profiles.append(
                    UserProfile.model_validate(
                        {
                            **data,
                            "uid": document.id,
                        }
                    )
                )
            except ValidationError:
                logger.warning("Skipped an invalid Firestore user profile")
        return profiles
    except FirebaseUnavailableError as exc:
        logger.error("Firestore is unavailable while listing user profiles: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User profile service is not configured.",
        ) from exc
    except Exception as exc:
        logger.exception("Could not list Firebase user profiles")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User profile service is temporarily unavailable.",
        ) from exc


@router.patch(
    "/{uid}/role",
    response_model=UserProfile,
    dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))],
)
def update_user_role(
    uid: str,
    payload: UserRoleUpdate,
    actor: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    if uid == actor.uid:
        raise HTTPException(status_code=409, detail="You cannot change your own role.")
    try:
        database = get_firebase_client().get_database()
        ref = database.collection("users").document(uid)
        snapshot = ref.get()
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="User profile not found.")
        data = snapshot.to_dict() or {}
        if payload.tenant_id and not database.collection("tenants").document(payload.tenant_id).get().exists:
            raise HTTPException(status_code=422, detail="Tenant does not exist.")
        updates = {
            "role": payload.role.value,
            "tenant_id": payload.tenant_id,
            "status": payload.status.value,
            "updated_at": datetime.now(timezone.utc),
        }
        batch = database.batch()
        batch.update(ref, updates)
        batch.create(
            database.collection("audit_logs").document(str(uuid4())),
            {
                "tenant_id": payload.tenant_id or data.get("tenant_id"),
                "actor_uid": actor.uid,
                "action": "user.role.update",
                "resource_type": "user",
                "resource_id": uid,
                "timestamp": updates["updated_at"],
                "result": "success",
            }
        )
        batch.commit()
        return UserProfile.model_validate({**data, **updates, "uid": uid})
    except FirebaseUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User profile service is not configured.",
        ) from exc
