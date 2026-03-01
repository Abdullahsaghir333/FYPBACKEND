from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.realtime import connect, disconnect

router = APIRouter()


@router.websocket("/{session_id}/ws")
async def session_ws(session_id: str, websocket: WebSocket) -> None:
    try:
        await connect(session_id, websocket)
        while True:
            # Keep the connection alive; clients may send pings or messages.
            await websocket.receive_text()
    except WebSocketDisconnect:
        disconnect(session_id, websocket)
    except Exception:
        disconnect(session_id, websocket)
