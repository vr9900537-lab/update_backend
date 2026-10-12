import json
import logging
import os
from functools import lru_cache
from typing import Any

from firebase_admin import credentials, firestore, get_app, initialize_app

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class FirebaseUnavailableError(RuntimeError):
    """Raised when the Firebase Admin SDK cannot be configured."""


class FirebaseClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._app: Any | None = None
        self._db: Any | None = None
        self._error: str | None = None

    def initialize(self) -> Any | None:
        if self._db is not None:
            return self._db

        project_id = self.settings.firebase_project_id
        if not project_id:
            self._error = "FIREBASE_PROJECT_ID is not configured."
            return None

        if self.settings.firebase_emulator_host:
            os.environ["FIRESTORE_EMULATOR_HOST"] = self.settings.firebase_emulator_host
        if self.settings.firebase_auth_emulator_host:
            os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = (
                self.settings.firebase_auth_emulator_host
            )

        try:
            credential = self._build_credential()
            if credential is None:
                if self._error is None:
                    self._error = (
                        "Firebase credentials are unavailable. Configure Application "
                        "Default Credentials, FIREBASE_CREDENTIALS_PATH, or "
                        "FIREBASE_CREDENTIALS_JSON."
                    )
                return None

            try:
                app = get_app()
            except ValueError:
                app = initialize_app(
                    credential=credential,
                    options={"projectId": self.settings.firebase_project_id},
                )

            if app.project_id != project_id:
                self._error = "The initialized Firebase app uses a different project."
                return None

            self._app = app
            self._db = firestore.client(app=app)
            self._error = None
            return self._db
        except Exception as exc:  # pragma: no cover - environment-dependent
            self._error = str(exc)
            return None

    def _build_credential(self) -> Any | None:
        if self.settings.firebase_credentials_json:
            try:
                service_account = json.loads(self.settings.firebase_credentials_json)
                return credentials.Certificate(service_account)
            except Exception as exc:  # pragma: no cover - validation path
                self._error = f"Invalid Firebase credentials: {exc}"
                return None

        credentials_path = (
            self.settings.firebase_credentials_path
            or self.settings.google_application_credentials
        )
        if credentials_path:
            try:
                return credentials.Certificate(credentials_path)
            except Exception as exc:  # pragma: no cover - environment-dependent
                self._error = str(exc)
                return None

        # Application Default Credentials support local gcloud auth, workload
        # identity, and GOOGLE_APPLICATION_CREDENTIALS without storing keys here.
        try:
            return credentials.ApplicationDefault()
        except Exception as exc:  # pragma: no cover - environment-dependent
            self._error = f"Application Default Credentials are unavailable: {exc}"
            return None

    def get_app(self) -> Any:
        if self.initialize() is None:
            raise FirebaseUnavailableError(self._error or "Firebase is unavailable.")
        return self._app

    def get_database(self) -> Any:
        database = self.initialize()
        if database is None:
            raise FirebaseUnavailableError(self._error or "Firestore is unavailable.")
        return database

    def status(self) -> dict[str, Any]:
        db = self.initialize()
        if db is None:
            return {
                "status": "not_configured",
                "project_id": self.settings.firebase_project_id,
                "details": "Firebase credentials or project configuration are unavailable.",
            }

        try:
            # Keep health checks bounded when Firestore is unreachable.
            collections = list(db.collections(timeout=2))
            return {
                "status": "connected",
                "project_id": self.settings.firebase_project_id,
                "collections_found": len(collections),
            }
        except Exception as exc:  # pragma: no cover - environment-dependent
            logger.warning(
                "Firestore health check failed (%s)", type(exc).__name__
            )
            return {
                "status": "error",
                "project_id": self.settings.firebase_project_id,
                "details": "Firestore could not be reached.",
            }


@lru_cache
def get_firebase_client() -> FirebaseClient:
    return FirebaseClient()
