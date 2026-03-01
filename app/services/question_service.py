import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.core.llm import llm
from app.models import QuestionRequest, QuestionResponse, SessionState
from app.services.notes_pipeline import _parse_json_from_llm, _llm_invoke_cached


async def answer_student_question(
    session: SessionState,
    payload: QuestionRequest,
) -> QuestionResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty.")

    slide_index = payload.slide_index or 0
    point_index = payload.point_index or 0

    slides: List[Dict[str, Any]] = [s.model_dump() for s in session.slides]
    current_slide: Optional[Dict[str, Any]] = slides[slide_index] if 0 <= slide_index < len(slides) else None

    system = (
        "You are an AI teacher currently giving a lesson based on the provided notes and slides. "
        "A student has interrupted you with a question. "
        "You must:\n"
        "1) Answer the question briefly (equivalent to a 1 to 2 minute speech), using the EASIEST tone like talking to a lay person.\n"
        "2) Provide short, strictly summarized bullet points (key points) that summarize your answer for a whiteboard display.\n"
        "Return STRICT JSON only, no extra commentary:\n"
        "{\n"
        '  \"answer\": \"your spoken-style answer in a lay man tone\",\n'
        '  \"whiteboard_plan\": \"3 to 4 extremely short bullet points\",\n'
        '  \"resume_from_slide_index\": number | null,\n'
        '  \"resume_from_point_index\": number | null\n'
        "}\n"
    )

    context_parts = [
        f"Student question: {question}",
        "",
        "Original notes (excerpt):",
        session.notes_text[:4000],
        "",
        "Slide deck structure:",
        json.dumps(slides, ensure_ascii=False)[:4000],
        "",
        f"Current slide index: {slide_index}",
        f"Current point index: {point_index}",
    ]
    if current_slide:
        context_parts.append("")
        context_parts.append("Current slide you were on:")
        context_parts.append(json.dumps(current_slide, ensure_ascii=False))

    human_prompt = "\n".join(context_parts)
    raw = _llm_invoke_cached(system, human_prompt)
    data: Dict[str, Any] = _parse_json_from_llm(raw)

    answer = str(data.get("answer") or "").strip()
    whiteboard_plan = str(data.get("whiteboard_plan") or "").strip()
    resume_from_slide_index = data.get("resume_from_slide_index")
    resume_from_point_index = data.get("resume_from_point_index")

    return QuestionResponse(
        answer=answer,
        whiteboard_plan=whiteboard_plan,
        resume_from_slide_index=resume_from_slide_index,
        resume_from_point_index=resume_from_point_index,
    )

