from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import base64
import numpy as np
import cv2
from app.services.focus_tracker import FocusTracker
import json

router = APIRouter()

# In-memory storage for FocusTracker instances keyed by session_id
_TRACKERS = {}

@router.websocket("/ws/{session_id}")
async def focus_ws(session_id: str, websocket: WebSocket):
    await websocket.accept()
    
    if session_id not in _TRACKERS:
        _TRACKERS[session_id] = FocusTracker()
    
    tracker = _TRACKERS[session_id]
    
    try:
        while True:
            # Receive base64 frame from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "reset":
                tracker.reset_calibration()
                await websocket.send_json({"status": "RECALIBRATING"})
                continue
                
            # Accept both `frame` (preferred) and `image` (legacy) keys from the client.
            frame_base64 = message.get("frame") or message.get("image")
            if not frame_base64:
                continue
            
            # Decode base64 to image
            encoded_data = frame_base64.split(',')[1] if ',' in frame_base64 else frame_base64
            nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                continue
                
            # Process frame
            results = tracker.process_frame(frame)
            
            # Send results back
            await websocket.send_json(results)
            
    except WebSocketDisconnect:
        # We keep the tracker instance in case the client reconnects
        pass
    except Exception as e:
        print(f"Error in focus_ws: {e}")
        try:
            await websocket.close()
        except:
            pass
