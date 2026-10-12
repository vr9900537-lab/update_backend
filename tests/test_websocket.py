import pytest

from app.websockets.manager import ConnectionManager


class FakeWebSocket:
    def __init__(self, should_fail: bool = False) -> None:
        self.events: list[dict[str, object]] = []
        self.should_fail = should_fail

    async def send_json(self, event: dict[str, object]) -> None:
        if self.should_fail:
            raise RuntimeError("closed")
        self.events.append(event)


@pytest.mark.anyio
async def test_manager_broadcasts_within_tenant() -> None:
    manager = ConnectionManager()
    socket = FakeWebSocket()
    await manager.connect("tenant-a", socket)  # type: ignore[arg-type]

    await manager.publish("tenant-a", {"type": "location"})

    assert socket.events == [{"type": "location"}]


@pytest.mark.anyio
async def test_manager_removes_failed_connections() -> None:
    manager = ConnectionManager()
    socket = FakeWebSocket(should_fail=True)
    await manager.connect("tenant-a", socket)  # type: ignore[arg-type]

    await manager.publish("tenant-a", {"type": "location"})

    assert "tenant-a" not in manager._connections
