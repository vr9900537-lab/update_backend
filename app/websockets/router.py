import asyncio
import logging
from typing import Any

from firebase_admin import auth as firebase_auth
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.firebase import FirebaseUnavailableError, get_firebase_client
from app.core.permissions import TRACKING_READ_ROLES
from app.schemas.users import UserProfile, UserStatus
from app.websockets.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tracking websocket"])


@router.websocket("/ws/tracking")
async def tracking_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    tenant_id: str | None = None
    try:
        message = await websocket.receive_json()
        token = message.get("token") if isinstance(message, dict) else None
        if not isinstance(token, str) or not token:
            await websocket.close(code=1008, reason="Firebase ID token required")
            return
        client = get_firebase_client()
        claims = firebase_auth.verify_id_token(
            token,
            app=client.get_app(),
            check_revoked=True,
        )
        uid = claims.get("uid")
        if not isinstance(uid, str):
            await websocket.close(code=1008, reason="Invalid identity")
            return
        snapshot = client.get_database().collection("users").document(uid).get()
        data: Any = snapshot.to_dict() if snapshot.exists else None
        if not isinstance(data, dict):
            await websocket.close(code=1008, reason="User profile required")
            return
        profile = UserProfile.model_validate({**data, "uid": uid})
        if profile.status != UserStatus.ACTIVE or not profile.tenant_id:
            await websocket.close(code=1008, reason="Active tenant profile required")
            return
        if profile.role not in TRACKING_READ_ROLES:
            await websocket.close(code=1008, reason="Tracking permission required")
            return
        tenant_id = profile.tenant_id
        await manager.connect(tenant_id, websocket)
        await websocket.send_json({"type": "connected"})
        awaiting_pong = False
        while True:
            try:
                incoming = await asyncio.wait_for(
                    websocket.receive_json(), timeout=30
                )
            except TimeoutError:
                if awaiting_pong:
                    await websocket.close(code=1001, reason="Heartbeat timeout")
                    return
                await websocket.send_json({"type": "heartbeat"})
                awaiting_pong = True
                continue
            if isinstance(incoming, dict) and incoming.get("type") in {"ping", "pong"}:
                awaiting_pong = False
                if incoming.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except (
        FirebaseUnavailableError,
        firebase_auth.InvalidIdTokenError,
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.RevokedIdTokenError,
        firebase_auth.UserDisabledError,
        ValidationError,
    ):
        logger.info("Rejected tracking WebSocket authentication")
        await websocket.close(code=1008, reason="Authentication failed")
    except Exception:
        logger.exception("Tracking WebSocket failed")
        await websocket.close(code=1011, reason="WebSocket service unavailable")
    finally:
        if tenant_id:
            manager.disconnect(tenant_id, websocket)
