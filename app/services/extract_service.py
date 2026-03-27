import os
import io
from typing import Optional, Dict, Tuple
import asyncio

from google import genai
from google.genai import types

# initialize client lazily
_client: Optional[genai.Client] = None

# simple in-memory cache for extractions (avoid repeated API calls on same file)
_extraction_cache: dict[str, Tuple[str, Optional[int]]] = {}

def get_genai_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in environment")
        _client = genai.Client(api_key=api_key)
    return _client


def get_pdf_page_count(data: bytes) -> Optional[int]:
    """Efficiently read just the PDF headers to count pages without full text extraction."""
    try:
        from pypdf import PdfReader
        pdf = PdfReader(io.BytesIO(data))
        return len(pdf.pages)
    except Exception as e:
        print(f"Warning: Failed to count PDF pages: {e}")
        return None


async def extract_text_from_bytes(data: bytes, mime_type: str) -> Tuple[str, Optional[int]]:
    """Extract text from binary data (PDF, image, etc.) using Gemini.

    Runs the blocking API call in a thread pool so it can be awaited from
    async endpoints.

    Responses are cached by sha256(data)+mime_type key to avoid spamming the
    API when the same file is uploaded repeatedly during development.
    """
    import hashlib

    key = hashlib.sha256(data).hexdigest() + "|" + mime_type
    if key in _extraction_cache:
        print(f"extract_text_from_bytes: cache hit {key[:8]}...")
        return _extraction_cache[key]

    def _call() -> str:
        client = get_genai_client()
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=[
                    f"Extract ALL text from this file (mime type {mime_type}) accurately.",
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                ],
            )
            return response.text
        except Exception as exc:
            # return error string so caller can log / raise HTTP 500 with details
            return f"Extraction Error: {exc}"

    # Attempt to get page count if it is a PDF
    page_count = None
    if mime_type == "application/pdf":
        page_count = get_pdf_page_count(data)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _call)
    _extraction_cache[key] = (result, page_count)
    print(f"extract_text_from_bytes: call complete, cached key {key[:8]}...")
    return result, page_count
