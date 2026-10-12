from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.firebase import get_firebase_client
from app.schemas.users import UserProfile

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=UserProfile)
def auth_me(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    return current_user


@router.get("/health")
def auth_health() -> dict[str, Any]:
    return {"firebase": get_firebase_client().status()}
