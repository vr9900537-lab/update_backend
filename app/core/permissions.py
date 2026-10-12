from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.auth import get_current_user
from app.schemas.users import UserProfile, UserRole


MANAGEMENT_ROLES = (
    UserRole.SUPER_ADMIN,
    UserRole.ADMIN,
    UserRole.POLICE_ADMINISTRATOR,
)
OPERATIONS_ROLES = (
    *MANAGEMENT_ROLES,
    UserRole.SUPERVISOR,
    UserRole.OPERATOR,
    UserRole.MONITORING_OFFICER,
)
TRACKING_READ_ROLES = (
    *OPERATIONS_ROLES,
    UserRole.VIEWER,
)


def require_roles(*allowed_roles: UserRole) -> Callable[..., UserProfile]:
    def role_dependency(
        current_user: Annotated[UserProfile, Depends(get_current_user)],
    ) -> UserProfile:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this operation.",
            )
        return current_user

    return role_dependency
