import json
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import time

from fastapi import HTTPException, UploadFile

from app.core.llm import llm
import re
from typing import List, Dict, Any

# Simple LLM response cache to avoid hitting quota limits during dev
_llm_cache: Dict[str, str] = {}
MAX_CLEANUP_CHARS = 12000
MAX_SLIDE_CHARS = 18000
MAX_SCRIPT_CHARS = 12000


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
    
    max_retries = 5
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
                    wait_time = 2 ** attempt * 2 # 2s, 4s, 8s, 16s
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


def _truncate_for_llm(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    # Keep head + tail for context continuity
    head = int(limit * 0.75)
    tail = limit - head
    return f"{t[:head]}\n\n[...truncated...]\n\n{t[-tail:]}"


def _fallback_slide_outline(notes_text: str, page_count: Optional[int] = None) -> List[Dict[str, Any]]:
    """Deterministic fallback when LLM is temporarily unavailable."""
    target = 6
    if page_count and page_count > 3:
        target = min(max(3, page_count), 20)
    lines = [ln.strip(" -•\t") for ln in (notes_text or "").splitlines() if ln.strip()]
    points_pool = [ln for ln in lines if len(ln) > 3][: target * 6]
    if not points_pool:
        points_pool = ["Overview", "Key concepts", "Examples", "Takeaways"] * target

    slides: List[Dict[str, Any]] = []
    idx = 0
    for i in range(target):
        title = f"Topic {i + 1}"
        if idx < len(points_pool):
            # first usable line as pseudo-title
            maybe_title = points_pool[idx]
            if 6 <= len(maybe_title) <= 80:
                title = maybe_title[:80]
                idx += 1
        pts = points_pool[idx: idx + 4]
        if not pts:
            pts = ["Key point 1", "Key point 2", "Key point 3"]
        idx += 4
        slides.append({"title": title, "points": pts})
    return slides


def _fallback_scripts(slides: List[Dict[str, Any]]) -> List[str]:
    scripts: List[str] = []
    for s in slides:
        title = str(s.get("title") or "this topic")
        points = s.get("points") or []
        point_text = "; ".join(str(p) for p in points[:4])
        scripts.append(
            f"In this slide, we cover {title}. Focus on these key ideas: {point_text}. "
            "Take a short pause after each point and relate it to a practical example."
        )
    return scripts


async def _llm_invoke_cached_async(system: str, human: str) -> str:
    """Async wrapper with robust retries.

    Uses the sync invoke in a worker thread to avoid occasional async transport
    warnings seen in some dependency stacks under heavy retry/cancellation.
    """
    import asyncio
    key = _cache_key(system, human)
    if key in _llm_cache:
        print(f"llm_invoke_cached_async: cache hit for key {key[:8]}...")
        return _llm_cache[key]

    max_retries = 5
    for attempt in range(max_retries):
        try:
            result = await asyncio.to_thread(llm.invoke, [("system", system), ("human", human)])
            response_text = _extract_text_from_result(result)
            _llm_cache[key] = response_text
            print(f"llm_invoke_cached_async: cache miss for key {key[:8]}...; cached response")
            return response_text
        except Exception as e:
            err_str = str(e)
            print(f"llm_invoke_cached_async: error: {err_str}")
            is_retryable = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str or "UNAVAILABLE" in err_str
            if is_retryable:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt * 2 # 2s, 4s, 8s, 16s
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
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            raise HTTPException(status_code=429, detail="AI Provider Rate Limit Exceeded. Please wait a minute and try again.")
        raise HTTPException(status_code=500, detail=text)

    # clean up text with LLM
    system = (
        "You receive raw text extracted from user notes. "
        "Your task is to clean it up into readable study notes, removing obvious noise, headers, and footers. "
        "Return ONLY the cleaned text, no explanations or extra commentary."
    )
    text_for_cleanup = _truncate_for_llm(text, MAX_CLEANUP_CHARS)
    try:
        cleaned = await _llm_invoke_cached_async(system, text_for_cleanup)
    except HTTPException as e:
        if e.status_code == 503:
            # Graceful fallback for very large files or temporary provider spikes.
            print("extract_text_from_upload: cleanup LLM unavailable, using extracted text directly.")
            cleaned = text_for_cleanup
        else:
            raise
    return cleaned.strip(), page_count


async def extract_text_from_bytes_upload(
    raw: bytes,
    filename: str,
    content_type: str,
) -> Tuple[str, Optional[int]]:
    """Like extract_text_from_upload, but works from raw bytes (safe for background tasks)."""
    if raw is None or len(raw) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file appears to be empty or non-text.")

    page_count = None
    text = ""
    ct = content_type or ""
    name = (filename or "").lower()

    print(f"extract_text_from_bytes_upload: received file '{filename}' content_type={ct} size={len(raw)}")
    if ct.startswith("text/") or name.endswith(".txt"):
        print("extract_text_from_bytes_upload: treating as plain text")
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"Could not decode file: {exc}") from exc
    elif "pdf" in ct or name.endswith(".pdf"):
        print("extract_text_from_bytes_upload: invoking PDF extractor")
        from app.services.extract_service import extract_text_from_bytes

        text, page_count = await extract_text_from_bytes(raw, "application/pdf")
        print(f"extract_text_from_bytes_upload: extractor returned {len(text)} chars, pages={page_count}")
    elif ct.startswith("image/") or any(name.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]):
        print("extract_text_from_bytes_upload: invoking image extractor")
        from app.services.extract_service import extract_text_from_bytes

        text, _ = await extract_text_from_bytes(raw, ct or "image/jpeg")
        print(f"extract_text_from_bytes_upload: extractor returned {len(text)} chars")
    else:
        print("extract_text_from_bytes_upload: unknown type, attempting decode")
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Uploaded file appears to be empty or non-text.")

    if isinstance(text, str) and text.startswith("Extraction Error"):
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            raise HTTPException(status_code=429, detail="AI Provider Rate Limit Exceeded. Please wait a minute and try again.")
        raise HTTPException(status_code=500, detail=text)

    system = (
        "You receive raw text extracted from user notes. "
        "Your task is to clean it up into readable study notes, removing obvious noise, headers, and footers. "
        "Return ONLY the cleaned text, no explanations or extra commentary."
    )
    text_for_cleanup = _truncate_for_llm(text, MAX_CLEANUP_CHARS)
    try:
        cleaned = await _llm_invoke_cached_async(system, text_for_cleanup)
    except HTTPException as e:
        if e.status_code == 503:
            print("extract_text_from_bytes_upload: cleanup LLM unavailable, using extracted text directly.")
            cleaned = text_for_cleanup
        else:
            raise
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
    notes_for_slides = _truncate_for_llm(notes_text, MAX_SLIDE_CHARS)
    try:
        raw = await _llm_invoke_cached_async(system, notes_for_slides)
    except HTTPException as e:
        if e.status_code == 503:
            print("generate_slides_from_notes: LLM unavailable, using deterministic fallback slides.")
            return _fallback_slide_outline(notes_for_slides, page_count)
        raise
    data = _parse_json_from_llm(raw)
    slides = data.get("slides") or []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="Model did not return any slides.")
    return slides


async def generate_scripts_for_slides(notes_text: str, slides: List[Dict[str, Any]], difficulty: str = 'medium') -> List[str]:
    # Build difficulty-aware prompt modifier
    difficulty_modifier = ""
    if difficulty == 'easy':
        difficulty_modifier = (
            "IMPORTANT: The student has selected EASY difficulty. "
            "Explain like you're talking to a high school student. "
            "Use very simple language, lots of analogies, and real-world examples. "
            "Avoid jargon. Keep sentences short.\n"
        )
    elif difficulty == 'hard':
        difficulty_modifier = (
            "IMPORTANT: The student has selected HARD difficulty. "
            "Explain at a university/graduate level. "
            "Use precise technical vocabulary, include formal definitions, "
            "and reference theoretical frameworks where applicable.\n"
        )

    system = (
        "You are an experienced teacher giving a spoken explanation.\n"
        f"{difficulty_modifier}"
        "For each slide, produce a short script (max ~200 words) that a teacher would say while presenting it.\n"
        "The scripts should be concise and to the point.\n"
        "Follow a teacher style explaining in layman language.\n"
        "ALWAYS try to use concrete, real-world examples to explain the points whenever applicable.\n"
        "Use approachable language, relatable examples, and small checkpoints like “pause and think for a second”.\n"
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
        f"Here are the cleaned notes:\n\n{_truncate_for_llm(notes_text, MAX_SCRIPT_CHARS)}\n\n"
        f"Here is the slide structure you already proposed:\n\n{slides_preview}"
    )
    try:
        raw = await _llm_invoke_cached_async(system, human_prompt)
    except HTTPException as e:
        if e.status_code == 503:
            print("generate_scripts_for_slides: LLM unavailable, using fallback scripts.")
            return _fallback_scripts(slides)
        raise
    data = _parse_json_from_llm(raw)
    scripts = data.get("scripts") or []
    if not isinstance(scripts, list) or len(scripts) != len(slides):
        raise HTTPException(status_code=500, detail="Model did not return matching scripts for slides.")
    return scripts


async def generate_notes_from_bookmarks(
    notes_text: str,
    slides: List[Dict[str, Any]],
    bookmarks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Generate structured study notes from student-bookmarked points using the LLM."""
    # keep payload small
    bm = []
    for b in bookmarks or []:
        if not isinstance(b, dict):
            continue
        text = str(b.get("content") or b.get("text") or "").strip()
        if not text:
            continue
        bm.append({
            "slideIndex": b.get("slideIndex"),
            "pointIndex": b.get("pointIndex"),
            "slideTitle": b.get("slideTitle"),
            "content": text[:500],
        })
    bm = bm[:80]

    slides_compact = []
    for s in slides or []:
        if not isinstance(s, dict):
            continue
        slides_compact.append({
            "title": str(s.get("title") or "")[:120],
            "points": (s.get("points") or [])[:10],
        })
    slides_compact = slides_compact[:50]

    system = (
        "You are an expert study-notes writer.\n"
        "You will receive:\n"
        "- the original cleaned notes\n"
        "- the slide deck structure (titles + bullets)\n"
        "- a list of student BOOKMARKED important points (highest priority)\n\n"
        "Create high-quality study notes STRICT JSON with this exact shape:\n"
        "{\n"
        '  \"summary\": \"string (5-8 sentences)\",\n'
        '  \"keyPoints\": [\"...\"],\n'
        '  \"importantPoints\": [\"...\"],\n'
        '  \"topicNotes\": [{\"topic\": \"...\", \"content\": \"...\"}],\n'
        '  \"cheatsheet\": [{\"term\": \"...\", \"def\": \"...\"}]\n'
        "}\n\n"
        "Rules:\n"
        "- `importantPoints` MUST be derived from bookmarks (rewrite/merge/dedupe them).\n"
        "- Keep `keyPoints` concise (max 20).\n"
        "- `topicNotes`: DO NOT just regurgitate bullet points. Write 5-12 comprehensive topics. For EACH topic, you MUST explain the concept clearly and then provide a concrete, easy-to-understand REAL-WORLD EXAMPLE.\n"
        "- `cheatsheet`: 8-15 items, concise and exam-ready. You MUST include terms and definitions derived closely from the student's BOOKMARKS as the highest priority items in this list.\n"
        "- `cheatsheet` MUST be completely different from `topicNotes` and must ONLY contain short definitions/formulas, not paragraphs.\n"
        "- No extra text outside JSON."
    )

    human = (
        f"BOOKMARKS (highest priority):\n{json.dumps(bm, ensure_ascii=False)}\n\n"
        f"SLIDES:\n{json.dumps(slides_compact, ensure_ascii=False)}\n\n"
        f"ORIGINAL NOTES (excerpt):\n{notes_text[:6000]}"
    )
    raw = await _llm_invoke_cached_async(system, human)
    data = _parse_json_from_llm(raw)
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="LLM returned invalid notes JSON.")

    # defensive normalization
    data["summary"] = str(data.get("summary") or "").strip()
    for k in ["keyPoints", "importantPoints"]:
        v = data.get(k) or []
        if isinstance(v, str):
            v = [x.strip() for x in v.split("\n") if x.strip()]
        if not isinstance(v, list):
            v = []
        data[k] = [str(x).strip() for x in v if str(x).strip()]

    tn = data.get("topicNotes") or []
    if not isinstance(tn, list):
        tn = []
    norm_tn = []
    for item in tn[:20]:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        content = str(item.get("content") or "").strip()
        if topic and content:
            norm_tn.append({"topic": topic, "content": content})
    data["topicNotes"] = norm_tn

    cs = data.get("cheatsheet") or []
    if not isinstance(cs, list):
        cs = []
    norm_cs = []
    for item in cs[:30]:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        dfn = str(item.get("def") or "").strip()
        if term and dfn:
            norm_cs.append({"term": term, "def": dfn})
    data["cheatsheet"] = norm_cs

    return data


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
