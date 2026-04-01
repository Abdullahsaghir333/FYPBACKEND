"""Text-to-Speech service using edge-tts (high-quality Microsoft Azure neural voices) for audio generation.

This implementation uses `edge-tts` to synthesize MP3 audio into memory natively with asyncio.
It provides extremely realistic and expressive voices 100% free of charge.
"""
import os
from typing import AsyncGenerator, Optional
import asyncio
import edge_tts
from io import BytesIO
import base64

async def _synthesize_edge_tts(text: str, voice_id: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice_id)
    buf = BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()

async def convert_text_to_speech(
    text: str,
    language_code: str = "en-US",
    # Using ChristopherNeural as the default expressive, joyful male voice
    voice_name: str = "en-US-ChristopherNeural", 
    speak_rate: float = 1.0,
) -> bytes:
    """Convert text to speech using edge-tts and return MP3 bytes."""
    if not text or not text.strip():
        return b""

    audio_bytes = await _synthesize_edge_tts(text, voice_name)
    return audio_bytes


async def convert_scripts_to_audio(
    scripts: list[str],
    chunk_size: int = 4096,
    language_code: str = "en-US",
    voice_name: str = "en-US-ChristopherNeural",
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
    voice_name: str = "en-US-ChristopherNeural",
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
    voice_name: str = "en-US-ChristopherNeural",
) -> AsyncGenerator[str, None]:
    """Stream script as base64-encoded audio chunks (safe for JSON/WebSocket)."""
    async for chunk in stream_script_audio(
        script,
        chunk_size=chunk_size,
        language_code=language_code,
        voice_name=voice_name,
    ):
        yield base64.b64encode(chunk).decode("utf-8")

AVAILABLE_VOICES = {
    "en-US": ["en-US-ChristopherNeural", "en-US-EricNeural", "en-US-SteffanNeural"],
}
