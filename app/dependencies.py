"""Authentication and authorization dependencies used by API routes."""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.auth import get_current_user
from app.core.permissions import require_roles
from app.schemas.users import UserProfile, UserRole


def get_tenant_id(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
) -> str | None:
    """Return the caller's tenant, or None for a cross-tenant super-admin."""
    if current_user.role == UserRole.SUPER_ADMIN:
        return None
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not assigned to a tenant.",
        )
    return current_user.tenant_id


__all__ = ["get_current_user", "get_tenant_id", "require_roles"]
