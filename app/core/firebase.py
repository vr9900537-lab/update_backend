"""Compatibility exports for Firebase setup now defined in :mod:`app.firebase`."""

from app.firebase import (
    FirebaseClient,
    FirebaseUnavailableError,
    get_firebase_client,
)

__all__ = ["FirebaseClient", "FirebaseUnavailableError", "get_firebase_client"]
