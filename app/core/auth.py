import logging
from typing import Annotated, Any

from firebase_admin import auth as firebase_auth
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.schemas.users import UserProfile, UserStatus

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing Firebase ID token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> UserProfile:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    firebase_client = get_firebase_client()
    try:
        token_claims = firebase_auth.verify_id_token(
            credentials.credentials,
            app=firebase_client.get_app(),
            check_revoked=True,
        )
    except (
        firebase_auth.InvalidIdTokenError,
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.RevokedIdTokenError,
        firebase_auth.UserDisabledError,
        ValueError,
    ) as exc:
        logger.info("Rejected Firebase ID token: %s", type(exc).__name__)
        raise _unauthorized() from exc
    except FirebaseUnavailableError as exc:
        logger.error("Firebase authentication is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured.",
        ) from exc
    except Exception as exc:
        logger.exception("Firebase ID token verification failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable.",
        ) from exc

    uid = token_claims.get("uid")
    if not isinstance(uid, str) or not uid:
        raise _unauthorized()

    try:
        profile_snapshot = (
            firebase_client.get_database()
            .collection("users")
            .document(uid)
            .get()
        )
    except FirebaseUnavailableError as exc:
        logger.error("Firestore is unavailable while loading a user profile: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User profile service is not configured.",
        ) from exc
    except Exception as exc:
        logger.exception("Could not load a Firebase user profile")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User profile service is temporarily unavailable.",
        ) from exc

    if not profile_snapshot.exists:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An authorized user profile is required.",
        )

    profile_data: Any = profile_snapshot.to_dict()
    if not isinstance(profile_data, dict):
        profile_data = {}

    try:
        profile = UserProfile.model_validate(
            {
                **profile_data,
                "uid": uid,
                "email": token_claims.get("email", profile_data.get("email")),
            }
        )
    except ValidationError as exc:
        logger.warning("Rejected invalid Firestore user profile")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An authorized user profile is required.",
        ) from exc

    if profile.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This user account is inactive.",
        )

    return profile
