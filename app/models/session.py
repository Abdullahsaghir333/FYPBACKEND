from typing import List, Optional, Any, Dict

from pydantic import BaseModel


class SlidePoint(BaseModel):
    text: str


class Slide(BaseModel):
    id: int
    title: str
    points: List[SlidePoint]
    script: str
    # Optional timing information for each point to allow frontend to highlight
    # points while audio is playing. Each entry is a dict with keys:
    # {"point_index": int, "start_ms": int, "end_ms": int, "text": str}
    point_timings: Optional[List[Dict[str, Any]]] = None
    # Audio content (base64-encoded MP3) for the script
    audio_data: Optional[str] = None
    # Audio chunks for streaming (base64-encoded)
    audio_chunks: Optional[List[str]] = None


class SessionState(BaseModel):
    id: str
    notes_text: str
    slides: List[Slide]


class QuestionRequest(BaseModel):
    question: str
    slide_index: Optional[int] = None
    point_index: Optional[int] = None


class QuestionResponse(BaseModel):
    answer: str
    whiteboard_plan: str
    resume_from_slide_index: Optional[int] = None
    resume_from_point_index: Optional[int] = None

