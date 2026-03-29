from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import base64
import numpy as np
import cv2
from app.services.focus_tracker import FocusTracker
import json
import logging
import traceback

router = APIRouter()

# ── File logger — writes all focus errors to focus_errors.log ──
_log = logging.getLogger("focus_ws")
_log.setLevel(logging.DEBUG)
if not _log.handlers:
    _fh = logging.FileHandler("focus_errors.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
    _log.addHandler(_fh)

# In-memory storage for FocusTracker instances keyed by session_id
_TRACKERS = {}

@router.websocket("/ws/{session_id}")
async def focus_ws(session_id: str, websocket: WebSocket):
    await websocket.accept()
    _log.info(f"[{session_id}] WebSocket connected")
    
    if session_id not in _TRACKERS:
        _TRACKERS[session_id] = FocusTracker()
    
    tracker = _TRACKERS[session_id]
    
    try:
        while True:
            try:
                data = await websocket.receive_text()
            except Exception:
                _log.info(f"[{session_id}] WebSocket receive failed (client disconnected)")
                break
            try:
                message = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                continue
            
            if message.get("type") == "reset":
                tracker.reset_calibration()
                try:
                    await websocket.send_json({"status": "RECALIBRATING"})
                except Exception:
                    break
                continue
                
            # Accept both `frame` (preferred) and `image` (legacy) keys from the client.
            frame_base64 = message.get("frame") or message.get("image")
            if not frame_base64:
                continue
            
            try:
                # Decode base64 to image
                encoded_data = frame_base64.split(',')[1] if ',' in frame_base64 else frame_base64
                nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame is None:
                    continue
                    
                # Process frame
                results = tracker.process_frame(frame)
            except Exception as proc_err:
                _log.error(f"[{session_id}] Frame processing error:\n{traceback.format_exc()}")
                continue
            
            # Send results back
            try:
                await websocket.send_json(results)
            except Exception:
                _log.info(f"[{session_id}] WebSocket send failed (client disconnected)")
                break
            
    except WebSocketDisconnect:
        _log.info(f"[{session_id}] WebSocket disconnected normally")
    except Exception as e:
        _log.error(f"[{session_id}] Unexpected error:\n{traceback.format_exc()}")
        try:
            await websocket.close()
        except:
            pass

