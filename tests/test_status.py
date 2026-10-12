from app.device_integrations.simulator import simulated_location
from app.workers.offline_devices import mark_offline_devices
from datetime import datetime, timedelta, timezone


class EmptyQuery:
    def where(self, *args, **kwargs):
        return self

    def limit(self, count):
        return self

    def stream(self):
        return []


class FakeDatabase:
    def collection(self, name):
        return EmptyQuery()

    def batch(self):
        raise AssertionError("No batch expected for an empty result.")


def test_offline_worker_does_not_write_when_no_devices_are_stale() -> None:
    assert mark_offline_devices(FakeDatabase(), timeout_seconds=300) == 0


def test_simulator_marks_generated_data_as_simulated() -> None:
    location = simulated_location("C05-001", 17.385, 78.4867)

    assert location.source == "simulated"


class StaleSnapshot:
    id = "device-1"
    reference = "status-ref"

    def to_dict(self):
        return {
            "device_id": self.id,
            "tenant_id": "tenant-1",
            "connectivity_status": "online",
            "last_seen_at": datetime.now(timezone.utc) - timedelta(hours=1),
        }


class StaleQuery(EmptyQuery):
    def stream(self):
        return [StaleSnapshot()]


class FakeBatch:
    def __init__(self):
        self.updates = []
        self.creates = []

    def update(self, reference, data):
        self.updates.append((reference, data))

    def create(self, reference, data):
        self.creates.append((reference, data))

    def commit(self):
        pass


class StaleDatabase:
    def __init__(self):
        self.write_batch = FakeBatch()

    def collection(self, name):
        if name == "device_status":
            return StaleQuery()
        return StaleCollection()

    def batch(self):
        return self.write_batch


class StaleCollection(EmptyQuery):
    def document(self, document_id):
        return f"{self}-{document_id}"


def test_offline_worker_marks_status_and_creates_alert_and_mock_delivery() -> None:
    database = StaleDatabase()
    events = []

    count = mark_offline_devices(database, timeout_seconds=300, events=events)

    assert count == 1
    assert len(database.write_batch.updates) == 1
    assert len(database.write_batch.creates) == 3
    assert events[0]["type"] == "device.offline"
    assert events[0]["tenant_id"] == "tenant-1"
