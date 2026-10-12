from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class UserRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    OPERATOR = "operator"
    VIEWER = "viewer"
    POLICE_ADMINISTRATOR = "police_administrator"
    MONITORING_OFFICER = "monitoring_officer"
    AUTHORIZED_AUDITOR = "authorized_auditor"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    email: str | None = None
    display_name: str | None = None
    role: UserRole
    tenant_id: str | None = None
    status: UserStatus = UserStatus.ACTIVE

    @model_validator(mode="before")
    @classmethod
    def support_active_flag(cls, value: object) -> object:
        if isinstance(value, dict) and "status" not in value and "is_active" in value:
            value = {
                **value,
                "status": (
                    UserStatus.ACTIVE.value
                    if value["is_active"]
                    else UserStatus.INACTIVE.value
                ),
            }
        return value
