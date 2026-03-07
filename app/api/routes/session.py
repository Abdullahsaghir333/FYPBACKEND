import uuid
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.models import QuestionRequest, QuestionResponse, SessionState, Slide, SlidePoint
from app.services import (
    answer_student_question,
    extract_text_from_upload,
    generate_scripts_for_slides,
    generate_slides_from_notes,
    get_session,
    save_session,
    convert_scripts_to_audio,
    stream_script_audio,
    stream_script_audio_base64,
    convert_text_to_speech,
)
from app.services.notes_pipeline import generate_point_timings
from app.services.realtime import broadcast
from app.services.realtime import (
    broadcast_audio_chunk,
    broadcast_audio_stream_start,
    broadcast_audio_stream_end,
)
import asyncio


router = APIRouter()


@router.post("", response_model=SessionState, summary="Create a new teaching session from uploaded notes")
async def create_session(file: UploadFile = File(...)) -> SessionState:
    if file.size is not None and file.size == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    try:
        notes_text = await extract_text_from_upload(file)
        # log debug info
        print(f"create_session: extracted notes length {len(notes_text)} chars")
    except Exception as e:
        print(f"create_session: extract_text_from_upload failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    try:
        slide_dicts = await generate_slides_from_notes(notes_text)
        print(f"create_session: slides generated ({len(slide_dicts)})")
    except Exception as e:
        print(f"create_session: slide generation failed: {e}")
        import traceback
        traceback.print_exc()
        raise

    try:
        scripts = await generate_scripts_for_slides(notes_text, slide_dicts)
        print(f"create_session: scripts generated ({len(scripts)})")
    except Exception as e:
        print(f"create_session: script generation failed: {e}")
        import traceback
        traceback.print_exc()
        raise

    # Generate audio for scripts (parallel conversion)
    try:
        audio_results = await convert_scripts_to_audio(scripts)
        audio_map = {ar["script_index"]: ar for ar in audio_results}
    except Exception as e:
        # If audio generation fails, continue without audio but log the error
        print(f"Warning: Failed to generate audio: {e}")
        audio_map = {}

    slides: List[Slide] = []
    for idx, (s, script) in enumerate(zip(slide_dicts, scripts), start=0):
        title = s.get("title") or f"Slide {idx + 1}"
        raw_points = s.get("points") or []
        points = [SlidePoint(text=str(p)) for p in raw_points if str(p).strip()]
        # generate approximate timings for each point so frontend can highlight
        timings = generate_point_timings(script.strip(), raw_points)
        
        # Get audio data if available
        audio_data = audio_map.get(idx)
        slide = Slide(
            id=idx,
            title=title,
            points=points,
            script=script.strip(),
            point_timings=timings,
            audio_data=audio_data.get("audio_data") if audio_data else None,
            audio_chunks=audio_data.get("audio_chunks") if audio_data else None,
        )
        slides.append(slide)

    session_id = str(uuid.uuid4())
    state = SessionState(id=session_id, notes_text=notes_text, slides=slides)
    save_session(state)
    return state


@router.get("/{session_id}", response_model=SessionState, summary="Get an existing teaching session")
async def get_session_state(session_id: str) -> SessionState:
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")
    return state


@router.post(
    "/{session_id}/question",
    response_model=QuestionResponse,
    summary="Ask a question in the middle of the session",
)
async def ask_question(session_id: str, payload: QuestionRequest) -> QuestionResponse:
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")

    response = await answer_student_question(state, payload)

    # Broadcast the answer to any realtime clients for this session.
    try:
        await broadcast(session_id, {"type": "question_answer", "payload": response.model_dump()})
    except Exception:
        # best-effort; continue even if broadcast fails
        pass

    return response


@router.post(
    "/{session_id}/question/audio",
    summary="Generate sentence-chunked TTS audio for a Q&A answer",
)
async def stream_question_answer_audio(session_id: str, payload: dict):
    """Split the answer into sentence groups, generate TTS in parallel, return as JSON array.
    
    This achieves low latency — the frontend can start playing the first chunk
    while the backend continues generating the rest simultaneously.
    """
    import re
    import base64
    import asyncio

    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")

    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided.")

    # Split into sentences, then group into chunks of 2 sentences each
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    # Group into pairs of 2 sentences for reasonable chunk size
    chunks = []
    for i in range(0, len(sentences), 2):
        chunk = " ".join(sentences[i:i+2])
        chunks.append(chunk)
    
    if not chunks:
        chunks = [text]

    # Generate TTS for all chunks in parallel
    async def tts_chunk(chunk_text: str) -> str:
        audio_bytes = await convert_text_to_speech(chunk_text)
        return base64.b64encode(audio_bytes).decode("utf-8")

    audio_chunks = await asyncio.gather(*[tts_chunk(c) for c in chunks])

    from fastapi.responses import JSONResponse
    return JSONResponse(content={
        "chunks": list(audio_chunks),
        "count": len(audio_chunks),
    })


@router.get(
    "/{session_id}/slides/{slide_id}/audio",
    summary="Stream audio for a specific slide (MP3 format)",
)
async def stream_slide_audio(session_id: str, slide_id: int) -> StreamingResponse:
    """Stream the audio for a specific slide in MP3 format.
    
    This endpoint streams the pre-generated MP3 audio file for a slide's script
    in real-time, allowing the client to play it as it arrives.
    """
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")
    
    if slide_id < 0 or slide_id >= len(state.slides):
        raise HTTPException(status_code=404, detail="Slide not found.")
    
    slide = state.slides[slide_id]
    
    # Return the audio stream
    import base64
    async def serve_cached_audio(audio_base64: str):
        audio_bytes = base64.b64decode(audio_base64)
        chunk_size = 4096
        for i in range(0, len(audio_bytes), chunk_size):
            yield audio_bytes[i : i + chunk_size]

    if slide.audio_data:
        generator = serve_cached_audio(slide.audio_data)
    else:
        generator = stream_script_audio(slide.script)

    return StreamingResponse(
        generator,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f"inline; filename=slide_{slide_id}.mp3"
        },
    )


@router.get(
    "/{session_id}/slides/{slide_id}/audio/base64",
    summary="Get base64-encoded audio chunks for streaming via WebSocket",
)
async def stream_slide_audio_base64(session_id: str, slide_id: int) -> dict:
    """Get audio chunks as base64-encoded strings for WebSocket transmission.
    
    This endpoint returns audio chunks encoded as base64, which is safe for
    transmission over WebSocket connections.
    """
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")
    
    if slide_id < 0 or slide_id >= len(state.slides):
        raise HTTPException(status_code=404, detail="Slide not found.")
    
    slide = state.slides[slide_id]
    
    # Collect all chunks
    chunks = []
    async for chunk in stream_script_audio_base64(slide.script):
        chunks.append(chunk)
    
    return {
        "slide_id": slide_id,
        "audio_chunks": chunks,
        "chunk_count": len(chunks),
    }


@router.post(
    "/{session_id}/slides/{slide_id}/play",
    summary="Start broadcasting slide audio to realtime clients",
)
async def play_slide_audio(session_id: str, slide_id: int) -> dict:
    """Start broadcasting the slide's audio to any connected realtime clients.

    The broadcast runs in the background and sends base64-encoded audio chunks
    over the session websocket connections using the realtime broadcast helpers.
    """
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")

    if slide_id < 0 or slide_id >= len(state.slides):
        raise HTTPException(status_code=404, detail="Slide not found.")

    slide = state.slides[slide_id]

    async def _broadcast():
        try:
            await broadcast_audio_stream_start(session_id, slide_id)
            async for chunk in stream_script_audio_base64(slide.script):
                await broadcast_audio_chunk(session_id, slide_id, chunk)
            await broadcast_audio_stream_end(session_id, slide_id)
        except Exception:
            # best-effort broadcasting; swallow errors
            try:
                await broadcast_audio_stream_end(session_id, slide_id)
            except Exception:
                pass

    asyncio.create_task(_broadcast())
    return {"status": "started", "slide_id": slide_id}

