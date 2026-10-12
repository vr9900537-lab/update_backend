"""Seed synthetic device data into Firestore Emulator only."""

from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.firebase import get_firebase_client


def main() -> None:
    settings = get_settings()
    if not settings.firebase_emulator_host:
        raise RuntimeError("Refusing to seed data unless FIREBASE_EMULATOR_HOST is set.")

    database = get_firebase_client().get_database()
    now = datetime.now(timezone.utc)
    database.collection("tenants").document("demo-tenant").set(
        {
            "tenant_id": "demo-tenant",
            "name": "Demo Tenant",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        merge=True,
    )
    database.collection("devices").document("DEMO-C05-001").set(
        {
            "device_id": "DEMO-C05-001",
            "tenant_id": "demo-tenant",
            "device_type": "simulated",
            "status": "active",
            "assigned_person_id": None,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
    )
    print("Seeded synthetic DEMO-C05-001 in the Firestore Emulator.")


if __name__ == "__main__":
    main()
