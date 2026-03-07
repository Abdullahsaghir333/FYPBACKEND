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
        "1) Answer the question in detail using the EASIEST tone like talking to a lay person. "
        "The answer should be long enough for a 1-2 minute verbal explanation.\n"
        "2) Provide 3-4 bullet points that summarize your answer for a whiteboard slide.\n"
        "Return STRICT JSON only, no extra commentary:\n"
        "{\n"
        '  "bullet_points": ["point 1", "point 2", "point 3"],\n'
        '  "detail_ans": "your full spoken-style answer in a lay man tone (1-2 minutes worth of speech)"\n'
        "}\n"
    )

    context_parts = [
        f"Student question: {question}",
        "",
        "Original notes (excerpt):",
        session.notes_text[:1500],
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

    bullet_points = data.get("bullet_points") or []
    if isinstance(bullet_points, str):
        bullet_points = [bp.strip() for bp in bullet_points.split("\n") if bp.strip()]
    detail_ans = str(data.get("detail_ans") or "").strip()

    return QuestionResponse(
        bullet_points=bullet_points,
        detail_ans=detail_ans,
        resume_from_slide_index=slide_index,
        resume_from_point_index=point_index,
    )

