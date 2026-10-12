from typing import Any

from app.repositories.firestore import get_database


class DeviceRepository:
    """Small Firestore data-access layer; routes can migrate to it incrementally."""

    def __init__(self, database: Any | None = None) -> None:
        self.database = database or get_database()

    def get(self, device_id: str) -> dict[str, Any] | None:
        snapshot = self.database.collection("devices").document(device_id).get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict()

    def create(self, device_id: str, document: dict[str, Any]) -> None:
        self.database.collection("devices").document(device_id).create(document)
