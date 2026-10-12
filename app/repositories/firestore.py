from typing import Any

from app.core.firebase import FirebaseClient, get_firebase_client


def get_database(client: FirebaseClient | None = None) -> Any:
    return (client or get_firebase_client()).get_database()
