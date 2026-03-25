import json
from typing import Any, Dict, List
import hashlib
import time

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
    """Call LLM with caching and automatic retry on 429/503 quota errors."""
    key = _cache_key(system, human)
    if key in _llm_cache:
        print(f"llm_invoke_cached: cache hit for key {key[:8]}...")
        return _llm_cache[key]
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = llm.invoke([("system", system), ("human", human)])
            response_text = _extract_text_from_result(result)
            _llm_cache[key] = response_text
            print(f"llm_invoke_cached: cache miss for key {key[:8]}...; cached response")
            return response_text
        except Exception as e:
            err_str = str(e)
            is_retryable = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str or "UNAVAILABLE" in err_str
            if is_retryable:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt * 2 # 2s, 4s
                    print(f"llm_invoke_cached: API busy (attempt {attempt+1}/{max_retries}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise HTTPException(status_code=503, detail="Gemini API is currently busy or quota exceeded. Please wait a moment and try again.")
            raise


def _extract_text_from_result(result) -> str:
    """Extract text from a LangChain LLM result, handling both str and content-block formats."""
    if isinstance(result.content, str):
        return result.content
    elif isinstance(result.content, list):
        parts = []
        for block in result.content:
            if isinstance(block, dict) and 'text' in block:
                parts.append(block['text'])
            elif hasattr(block, 'text'):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(result.content)


async def _llm_invoke_cached_async(system: str, human: str) -> str:
    """Async version: uses ainvoke() so the event loop is never blocked."""
    import asyncio
    key = _cache_key(system, human)
    if key in _llm_cache:
        print(f"llm_invoke_cached_async: cache hit for key {key[:8]}...")
        return _llm_cache[key]

    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = await llm.ainvoke([("system", system), ("human", human)])
            response_text = _extract_text_from_result(result)
            _llm_cache[key] = response_text
            print(f"llm_invoke_cached_async: cache miss for key {key[:8]}...; cached response")
            return response_text
        except Exception as e:
            err_str = str(e)
            is_retryable = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str or "UNAVAILABLE" in err_str
            if is_retryable:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt * 2 # 2s, 4s
                    print(f"llm_invoke_cached_async: API busy (attempt {attempt+1}/{max_retries}). Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise HTTPException(status_code=503, detail="Gemini API is currently busy or quota exceeded. Please wait a moment and try again.")
            raise


def _parse_json_from_llm(text: str) -> Any:
    """Parse JSON from LLM output, handling common formatting issues."""
    stripped = text.strip()
    
    # 1. Strip markdown code fences (```json ... ``` or ``` ... ```)
    if stripped.startswith("```"):
        # Remove opening fence
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        # Remove closing fence
        if stripped.endswith("```"):
            stripped = stripped[:-3].rstrip()
    
    # 2. Try direct parse first
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    
    # 3. Try to find JSON object/array in the text (LLM may add commentary)
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start_idx = stripped.find(start_char)
        end_idx = stripped.rfind(end_char)
        if start_idx != -1 and end_idx > start_idx:
            candidate = stripped[start_idx:end_idx + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # 4. Try fixing single quotes -> double quotes
                fixed = candidate.replace("'", '"')
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass
                
                # 5. Try removing trailing commas before } or ]
                fixed2 = re.sub(r',\s*([}\]])', r'\1', fixed)
                try:
                    return json.loads(fixed2)
                except json.JSONDecodeError:
                    pass
    
    # All attempts failed — log the raw output for debugging
    print(f"_parse_json_from_llm: FAILED to parse. Raw LLM output:\n{text[:500]}")
    raise HTTPException(
        status_code=500,
        detail=f"LLM returned invalid JSON. Raw output starts with: {text[:200]}"
    )


from typing import Tuple, Optional

async def extract_text_from_upload(file: UploadFile) -> Tuple[str, Optional[int]]:
    """Read an uploaded file and return cleaned text and optional page count.

    This helper is used by the session creation flow. For plain-text files we
    simply decode the bytes; for binary formats such as PDF or images we call
    out to the Gemini extractor service to pull the text out of the document.
    After obtaining raw text, we send it thro   ugh the LLM cleanup step used
    previously so that headers/footers and noise are removed.
    """

    raw = await file.read()

    # determine whether we need to run extraction
    text = ""
    page_count = None
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

        text, page_count = await extract_text_from_bytes(raw, "application/pdf")
        print(f"extract_text_from_upload: extractor returned {len(text)} chars, pages={page_count}")
        print(f"--- EXTRACTED PDF TEXT PREVIEW ---\n{text[:1000]}\n----------------------------------")
    elif content_type.startswith("image/") or any(file.filename.lower().endswith(ext) for ext in ['.png','.jpg','.jpeg','.bmp','.tiff']):
        print("extract_text_from_upload: invoking image extractor")
        from app.services.extract_service import extract_text_from_bytes

        text, _ = await extract_text_from_bytes(raw, content_type or "image/jpeg")    
        print(f"extract_text_from_upload: extractor returned {len(text)} chars")
        print(f"--- EXTRACTED IMAGE TEXT PREVIEW ---\n{text[:1000]}\n------------------------------------")
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
    cleaned = await _llm_invoke_cached_async(system, text)
    return cleaned.strip(), page_count


async def generate_slides_from_notes(notes_text: str, page_count: Optional[int] = None) -> List[Dict[str, Any]]:
    page_instruction = ""
    if page_count is not None and page_count > 3:
        page_instruction = f"IMPORTANT: The original document has exactly {page_count} pages. You MUST generate EXACTLY {page_count} slides (one main slide representing each page's core concept).\n"

    system = (
        "You are an expert teacher. Given the student's notes, design a concise slide deck.\n"
        f"{page_instruction}"
        "Return STRICT JSON with this exact shape:\n"
        "{\n"
        '  \"slides\": [\n'
        "    {\n"
        '      \"title\": \"string\",\n'
        '      \"points\": [\"point 1\", \"point 2\", \"point 3\", \"point 4\", \"...\"] // Extract ALL key points from the source material for this slide. Do not limit to just 3-4 points if the source material has more points.\n'
        "    },\n"
        "    ...\n"
        "  ]\n"
        "}\n"
        "Do NOT include any explanations outside the JSON."
    )
    raw = await _llm_invoke_cached_async(system, notes_text)
    data = _parse_json_from_llm(raw)
    slides = data.get("slides") or []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="Model did not return any slides.")
    return slides


async def generate_scripts_for_slides(notes_text: str, slides: List[Dict[str, Any]]) -> List[str]:
    system = (
        "You are an experienced teacher giving a spoken explanation.\n"
        "For each slide, produce a short script (max ~200 words) that a teacher would say while presenting it.\n"
        "The scripts should be concise and to the point.\n"
        "Follow a teacher style  explaining in layman language and use simple examples.\n"
        "Use approachable language, examples, and small checkpoints like “pause and think for a second”.\n"
        "Return STRICT JSON with this exact structure:\n"
        "{\n"
        '  \"scripts\": [\"script for slide 1\", \"script for slide 2\", ...]\n'
        "}\n"
        f"IMPORTANT: You are generating scripts for a batch of EXACTLY {len(slides)} slides.\n"
        f"Your JSON array MUST contain EXACTLY {len(slides)} strings, one for each slide provided.\n"
        "No text outside the JSON object."
    )
    slides_preview = json.dumps(slides, ensure_ascii=False)
    human_prompt = (
        f"Here are the cleaned notes:\n\n{notes_text}\n\n"
        f"Here is the slide structure you already proposed:\n\n{slides_preview}"
    )
    raw = await _llm_invoke_cached_async(system, human_prompt)
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

