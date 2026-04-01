from typing import Any
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.models import QuestionRequest
from app.services import answer_student_question, get_session
from app.services.realtime import connect, disconnect, broadcast

router = APIRouter()


@router.websocket("/{session_id}/ws")
async def session_ws(session_id: str, websocket: WebSocket) -> None:
    try:
        await connect(session_id, websocket)
        while True:
            # Keep the connection alive; clients may send pings or messages.
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "question":
                    payload = msg.get("payload", {})
                    req = QuestionRequest(**payload)
                    state = get_session(session_id)
                    if state:
                        resp = await answer_student_question(state, req)
                        await broadcast(session_id, {"type": "question_answer", "payload": resp.model_dump()})
            except (json.JSONDecodeError, ValidationError):
                pass
    except WebSocketDisconnect:
        disconnect(session_id, websocket)
    except Exception:
        disconnect(session_id, websocket)
