from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, tenant_id: str, websocket: WebSocket) -> None:
        self._connections.setdefault(tenant_id, set()).add(websocket)

    def disconnect(self, tenant_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(tenant_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(tenant_id, None)

    async def publish(self, tenant_id: str, event: dict[str, object]) -> None:
        stale: list[WebSocket] = []
        for websocket in self._connections.get(tenant_id, set()):
            try:
                await websocket.send_json(event)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(tenant_id, websocket)


manager = ConnectionManager()
