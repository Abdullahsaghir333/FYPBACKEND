from app.services.notes_pipeline import (
    extract_text_from_upload,
    generate_scripts_for_slides,
    generate_slides_from_notes,
)
from app.services.question_service import answer_student_question
from app.services.session_store import get_session, save_session
from app.services.audio_service import (
    convert_text_to_speech,
    convert_scripts_to_audio,
    stream_script_audio,
    stream_script_audio_base64,
)

__all__ = [
    "extract_text_from_upload",
    "generate_slides_from_notes",
    "generate_scripts_for_slides",
    "answer_student_question",
    "get_session",
    "save_session",
    "convert_text_to_speech",
    "convert_scripts_to_audio",
    "stream_script_audio",
    "stream_script_audio_base64",
]

