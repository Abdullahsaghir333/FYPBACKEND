from typing import Dict, Set

from fastapi import WebSocket

# Simple in-memory WebSocket connection manager keyed by session_id.
_CONNECTIONS: Dict[str, Set[WebSocket]] = {}


async def connect(session_id: str, websocket: WebSocket) -> None:
    await websocket.accept()
    conns = _CONNECTIONS.setdefault(session_id, set())
    conns.add(websocket)


def disconnect(session_id: str, websocket: WebSocket) -> None:
    conns = _CONNECTIONS.get(session_id)
    if not conns:
        return
    conns.discard(websocket)
    if not conns:
        _CONNECTIONS.pop(session_id, None)


async def broadcast(session_id: str, message: dict) -> None:
    conns = list(_CONNECTIONS.get(session_id, []))
    for ws in conns:
        try:
            await ws.send_json(message)
        except Exception:
            # best-effort; ignore send errors
            pass


async def broadcast_audio_chunk(session_id: str, slide_id: int, chunk_data: str) -> None:
    """Broadcast an audio chunk to all connected clients for real-time playback.
    
    Args:
        session_id: The session ID
        slide_id: The slide ID for which audio is playing
        chunk_data: Base64-encoded audio chunk
    """
    message = {
        "type": "audio_chunk",
        "slide_id": slide_id,
        "audio_chunk": chunk_data,
    }
    await broadcast(session_id, message)


async def broadcast_audio_stream_start(session_id: str, slide_id: int) -> None:
    """Notify clients that audio streaming is starting for a slide."""
    message = {
        "type": "audio_stream_start",
        "slide_id": slide_id,
    }
    await broadcast(session_id, message)


async def broadcast_audio_stream_end(session_id: str, slide_id: int) -> None:
    """Notify clients that audio streaming has ended for a slide."""
    message = {
        "type": "audio_stream_end",
        "slide_id": slide_id,
    }
    await broadcast(session_id, message)

