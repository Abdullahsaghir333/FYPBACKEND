"""Text-to-Speech service using gTTS (lightweight Google TTS) for audio generation.

This implementation replaces the previous Google Cloud TTS client with the
`gTTS` package. It synthesizes MP3 audio into memory and returns bytes. To
keep the existing async API, the blocking gTTS calls are executed in a
ThreadPoolExecutor.
"""
import os
from typing import AsyncGenerator, Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
from gtts import gTTS
from io import BytesIO
import base64

_executor = ThreadPoolExecutor(max_workers=4)


async def convert_text_to_speech(
    text: str,
    language_code: str = "en-US",
    voice_name: str = "en-US-Neural2-A",
    speak_rate: float = 1.0,
) -> bytes:
    """Convert text to speech using gTTS and return MP3 bytes.

    Notes:
    - `gTTS` uses the short language code (e.g. 'en'). If a regional code is
      provided (e.g. 'en-US'), we use the base language.
    - `gTTS` does not support custom voice selection or speaking rate; those
      parameters are accepted for API compatibility but ignored.
    """
    if not text or not text.strip():
        return b""

    lang = language_code.split("-")[0] if language_code else "en"

    def _synthesize() -> bytes:
        buf = BytesIO()
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.write_to_fp(buf)
        return buf.getvalue()

    loop = asyncio.get_event_loop()
    audio_bytes = await loop.run_in_executor(_executor, _synthesize)
    return audio_bytes


async def convert_scripts_to_audio(
    scripts: list[str],
    chunk_size: int = 4096,
    language_code: str = "en-US",
    voice_name: str = "en-US-Neural2-A",
) -> list[dict]:
    """Convert multiple scripts to audio and return metadata with audio data."""
    results = []

    for idx, script in enumerate(scripts):
        audio_bytes = await convert_text_to_speech(
            script,
            language_code=language_code,
            voice_name=voice_name,
        )

        audio_chunks = [
            base64.b64encode(audio_bytes[i : i + chunk_size]).decode("utf-8")
            for i in range(0, len(audio_bytes), chunk_size)
        ]

        results.append({
            "script_index": idx,
            "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
            "audio_chunks": audio_chunks,
            "duration_seconds": None,
        })

    return results


async def stream_script_audio(
    script: str,
    chunk_size: int = 4096,
    language_code: str = "en-US",
    voice_name: str = "en-US-Neural2-A",
) -> AsyncGenerator[bytes, None]:
    """Stream script as audio chunks (yields raw MP3 bytes)."""
    audio_bytes = await convert_text_to_speech(
        script,
        language_code=language_code,
        voice_name=voice_name,
    )

    for i in range(0, len(audio_bytes), chunk_size):
        yield audio_bytes[i : i + chunk_size]


async def stream_script_audio_base64(
    script: str,
    chunk_size: int = 4096,
    language_code: str = "en-US",
    voice_name: str = "en-US-Neural2-A",
) -> AsyncGenerator[str, None]:
    """Stream script as base64-encoded audio chunks (safe for JSON/WebSocket)."""
    async for chunk in stream_script_audio(
        script,
        chunk_size=chunk_size,
        language_code=language_code,
        voice_name=voice_name,
    ):
        yield base64.b64encode(chunk).decode("utf-8")


# Note: gTTS uses language codes (e.g. 'en', 'en-uk'). We keep a simple map
# for compatibility, but voice selection is not available with gTTS.
AVAILABLE_VOICES = {
    "en-US": ["default"],
    "en-GB": ["default"],
}
