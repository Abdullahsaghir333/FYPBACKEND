import json
from typing import Any, Dict, List
import hashlib

from fastapi import HTTPException, UploadFile

from app.core.llm import llm
import re
from typing import List, Dict, Any

# Simple LLM response cache to avoid hitting quota limits during dev
_llm_cache: Dict[str, str] = {}


def _cache_key(system: str, human: str) -> str:
    """Generate a deterministic cache key from system and human prompts."""
    combined = f"{system}|||{human}"
    return hashlib.md5(combined.encode()).hexdigest()


def _llm_invoke_cached(system: str, human: str) -> str:
    """Call LLM with caching; returns the response text."""
    key = _cache_key(system, human)
    if key in _llm_cache:
        print(f"llm_invoke_cached: cache hit for key {key[:8]}...")
        return _llm_cache[key]
    
    # call LLM
    result = llm.invoke([("system", system), ("human", human)])
    response_text = result.content if isinstance(result.content, str) else "".join(map(str, result.content))
    _llm_cache[key] = response_text
    print(f"llm_invoke_cached: cache miss for key {key[:8]}...; cached response")
    return response_text


def _parse_json_from_llm(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            lines = stripped.splitlines()
            if lines:
                first = lines[0]
                if first.lower() in {"json", "js", "javascript", "ts", "typescript"}:
                    stripped = "\n".join(lines[1:])
        return json.loads(stripped)


async def extract_text_from_upload(file: UploadFile) -> str:
    """Read an uploaded file and return cleaned text.

    This helper is used by the session creation flow. For plain-text files we
    simply decode the bytes; for binary formats such as PDF or images we call
    out to the Gemini extractor service to pull the text out of the document.
    After obtaining raw text, we send it thro   ugh the LLM cleanup step used
    previously so that headers/footers and noise are removed.
    """

    raw = await file.read()

    # determine whether we need to run extraction
    text = ""
    content_type = file.content_type or ""
    print(f"extract_text_from_upload: received file '{file.filename}' content_type={content_type} size={len(raw)}")
    if content_type.startswith("text/") or file.filename.lower().endswith(".txt"):
        print("extract_text_from_upload: treating as plain text")
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"Could not decode file: {exc}") from exc
    elif "pdf" in content_type or file.filename.lower().endswith(".pdf"):
        print("extract_text_from_upload: invoking PDF extractor")
        from app.services.extract_service import extract_text_from_bytes

        text = await extract_text_from_bytes(raw, "application/pdf")
        print(f"extract_text_from_upload: extractor returned {len(text)} chars")
    elif content_type.startswith("image/") or any(file.filename.lower().endswith(ext) for ext in ['.png','.jpg','.jpeg','.bmp','.tiff']):
        print("extract_text_from_upload: invoking image extractor")
        from app.services.extract_service import extract_text_from_bytes

        text = await extract_text_from_bytes(raw, content_type or "image/jpeg")
        print(f"extract_text_from_upload: extractor returned {len(text)} chars")
    else:
        print("extract_text_from_upload: unknown type, attempting decode")
        # fallback to naive decode hoping for plaintext
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Uploaded file appears to be empty or non-text.")

    # if extractor returned an error message, pass it through
    if isinstance(text, str) and text.startswith("Extraction Error"):
        raise HTTPException(status_code=500, detail=text)

    # clean up text with LLM
    system = (
        "You receive raw text extracted from user notes. "
        "Your task is to clean it up into readable study notes, removing obvious noise, headers, and footers. "
        "Return ONLY the cleaned text, no explanations or extra commentary."
    )
    cleaned = _llm_invoke_cached(system, text)
    return cleaned.strip()


async def generate_slides_from_notes(notes_text: str) -> List[Dict[str, Any]]:
    system = (
        "You are an expert teacher. Given the student's notes, design a concise slide deck.\n"
        "Return STRICT JSON with this exact shape:\n"
        "{\n"
        '  \"slides\": [\n'
        "    {\n"
        '      \"title\": \"string\",\n'
        '      \"points\": [\"point 1\", \"point 2\", \"point 3\"] // strictly 3 to 4 points max\n'
        "    },\n"
        "    ...\n"
        "  ]\n"
        "}\n"
        "Do NOT include any explanations outside the JSON."
    )
    try:
        raw = _llm_invoke_cached(system, notes_text)
    except Exception as exc:
        # wrap and propagate to route
        raise HTTPException(status_code=500, detail=f"Slide generation error: {exc}")
    data = _parse_json_from_llm(raw)
    slides = data.get("slides") or []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="Model did not return any slides.")
    return slides


async def generate_scripts_for_slides(notes_text: str, slides: List[Dict[str, Any]]) -> List[str]:
    system = (
        "You are an experienced teacher giving a spoken explanation.\n"
        "For each slide, produce a short script (max ~200 words) that a teacher would say while presenting it.\n"
        "Use approachable language, examples, and small checkpoints like “pause and think for a second”.\n"
        "Return STRICT JSON with this exact structure:\n"
        "{\n"
        '  \"scripts\": [\"script for slide 1\", \"script for slide 2\", ...]\n'
        "}\n"
        "The number of scripts must exactly match the number of slides.\n"
        "No text outside the JSON object."
    )
    slides_preview = json.dumps(slides, ensure_ascii=False)
    human_prompt = (
        f"Here are the cleaned notes:\n\n{notes_text}\n\n"
        f"Here is the slide structure you already proposed:\n\n{slides_preview}"
    )
    try:
        raw = _llm_invoke_cached(system, human_prompt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Script generation error: {exc}")
    data = _parse_json_from_llm(raw)
    scripts = data.get("scripts") or []
    if not isinstance(scripts, list) or len(scripts) != len(slides):
        raise HTTPException(status_code=500, detail="Model did not return matching scripts for slides.")
    return scripts


def generate_point_timings(script: str, points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Estimate timing (ms) ranges for each slide point based on script text.

    This is a heuristic mapping: split the script into sentences, distribute
    sentences evenly across points weighted by word counts, and estimate
    duration using a words-per-minute assumption.
    """
    if not points:
        return []

    # Split script into sentences (very simple)
    sentences = [s.strip() for s in re.split(r'[\.\!\?]\s+', script) if s.strip()]
    if not sentences:
        # fallback: split by words
        words = script.split()
        total_words = len(words)
        words_per_point = max(1, total_words // len(points))
        timings = []
        word_index = 0
        wpm = 150
        ms_per_word = 60000 / wpm
        for idx, p in enumerate(points):
            chunk_words = words[word_index: word_index + words_per_point]
            wc = len(chunk_words)
            duration = int(wc * ms_per_word)
            start = int(word_index * ms_per_word)
            end = start + duration
            timings.append({
                "point_index": idx,
                "start_ms": start,
                "end_ms": end,
                "text": " ".join(chunk_words),
            })
            word_index += words_per_point
        return timings

    # assign sentences to points roughly evenly by total words
    sentence_word_counts = [len(s.split()) for s in sentences]
    total_words = sum(sentence_word_counts)
    if total_words == 0:
        return []

    # determine target words per point
    target_per_point = total_words / len(points)

    groups: List[List[int]] = []  # indices of sentences per point
    current_group: List[int] = []
    current_words = 0
    for i, wc in enumerate(sentence_word_counts):
        if current_words >= target_per_point and len(groups) < len(points) - 1:
            groups.append(current_group)
            current_group = []
            current_words = 0
        current_group.append(i)
        current_words += wc
    groups.append(current_group)

    # estimate timings
    wpm = 150
    ms_per_word = 60000 / wpm
    timings: List[Dict[str, Any]] = []
    elapsed = 0
    for point_idx, group in enumerate(groups):
        group_text = " ".join(sentences[i] for i in group)
        wc = sum(sentence_word_counts[i] for i in group)
        duration = int(wc * ms_per_word)
        start = elapsed
        end = start + duration
        timings.append({
            "point_index": point_idx,
            "start_ms": start,
            "end_ms": end,
            "text": group_text,
        })
        elapsed = end
    return timings

