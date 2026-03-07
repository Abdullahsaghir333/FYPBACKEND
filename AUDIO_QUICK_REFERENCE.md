# Audio System - Quick Reference Guide

## Overview

The text-to-speech audio system converts slide scripts to natural-sounding audio using Google Cloud Text-to-Speech API. Audio is generated automatically when you create a session.

## Key Features

- ✅ **Automatic Generation**: Audio is generated when slides are created
- ✅ **Multiple Formats**: 
  - Full audio data (base64) in session response
  - Pre-split chunks for streaming
  - Direct MP3 stream via REST API
  - Real-time WebSocket chunks
- ✅ **Real-Time Streaming**: Audio chunks delivered as they're processed
- ✅ **Synchronized Highlighting**: Point-level timing for UI highlighting
- ✅ **Multiple Access Methods**: REST API, WebSocket, pre-loaded session data

## Audio Pipeline

```
User Notes
    ↓
[Extract & Clean Text]
    ↓
[Generate Slides]
    ↓
[Generate Scripts for Slides]
    ↓
[Text-to-Speech Conversion] ← Google Cloud TTS API
    ↓
[Create Chunks/Base64 Encoding]
    ↓
[Store in SessionState]
    ↓
[Return to Client]
```

## Data Structures

### Session Response with Audio

```json
{
  "id": "session-uuid",
  "notes_text": "...",
  "slides": [
    {
      "id": 0,
      "title": "Introduction",
      "points": [
        { "text": "Point about topic" },
        { "text": "Another point" }
      ],
      "script": "Hello everyone, today we...",
      "point_timings": [
        {
          "point_index": 0,
          "start_ms": 0,
          "end_ms": 2400,
          "text": "Hello everyone"
        }
      ],
      "audio_data": "SUQzBAAAI1RTAVA...",  // Full MP3 as base64
      "audio_chunks": [
        "SUQzBAAAI1RTAVA...",  // Chunk 1
        "AAP+AAAA...",          // Chunk 2
        // ... more chunks
      ]
    }
  ]
}
```

### WebSocket Audio Messages

**Stream Start:**
```json
{
  "type": "audio_stream_start",
  "slide_id": 0
}
```

**Audio Chunk:**
```json
{
  "type": "audio_chunk",
  "slide_id": 0,
  "audio_chunk": "SUQzBAAAI1RTAVA..."
}
```

**Stream End:**
```json
{
  "type": "audio_stream_end",
  "slide_id": 0
}
```

## API Endpoints

### 1. Create Session (Includes Audio)
```
POST /sessions
Content-Type: multipart/form-data

file: <notes file>
```

**Response:** `SessionState` with audio_data and audio_chunks

**Time:** ~1-3 seconds per slide (includes TTS generation)

---

### 2. Stream Audio (MP3)
```
GET /sessions/{session_id}/slides/{slide_id}/audio
```

**Response:** Direct MP3 stream (audio/mpeg)

**Use Case:** Play audio without pre-generation delay

**Example:**
```javascript
const response = await fetch('/sessions/123/slides/0/audio');
const blob = await response.blob();
const audio = new Audio(URL.createObjectURL(blob));
audio.play();
```

---

### 3. Get Audio Chunks (REST)
```
GET /sessions/{session_id}/slides/{slide_id}/audio/base64
```

**Response:**
```json
{
  "slide_id": 0,
  "audio_chunks": ["chunk1...", "chunk2...", ...],
  "chunk_count": 42
}
```

**Use Case:** Batch processing or manual chunk control

---

### 4. WebSocket Connection
```
WS /realtime/{session_id}/ws
```

**Receive Messages:** `audio_stream_start`, `audio_chunk`, `audio_stream_end`

**Use Case:** Real-time audio streaming with live UI updates

## Implementation Patterns

### Pattern 1: Simple Playback (Easiest)
Use `slide.audio_data` from the session response.

```javascript
function playAudio(slide) {
  const bytes = new Uint8Array(atob(slide.audio_data).split('').map(c => c.charCodeAt()));
  const blob = new Blob([bytes], { type: 'audio/mpeg' });
  new Audio(URL.createObjectURL(blob)).play();
}
```

**Pros:** Simple, no additional requests
**Cons:** Larger session response, must wait for generation

---

### Pattern 2: On-Demand Streaming
Stream audio only when needed via REST API.

```javascript
async function streamAudio(sessionId, slideId) {
  const response = await fetch(`/sessions/${sessionId}/slides/${slideId}/audio`);
  const blob = await response.blob();
  new Audio(URL.createObjectURL(blob)).play();
}
```

**Pros:** Smaller session responses, generates only when played
**Cons:** Network latency, client must request each audio

---

### Pattern 3: Real-Time WebSocket
Get chunks as they're generated, excellent for progress UI.

---

## Student Interruption & Q&A Workflow

The front-end listens continuously with the Web Speech API and behaves like a real
voice assistant:

1. **Interrupt detection.** As soon as any speech is detected (`onspeechstart`) the
   current slide audio is paused and the UI enters a `listening` state.
2. **Silence buffering.** All transcripts are appended to a buffer and a 5‑second
   timer is reset after each phrase. When the student stops speaking for 5 seconds
   we consider the question complete and POST it to `/session/{id}/question`.
3. **Answering.** The backend replies with an `answer` and optional
   `resume_from_*` indices. The client speaks (or simulates) the answer, then
   transitions to a confirmation state.
4. **Confirmation.** After answering the user is asked “Is that clear?”. Speech is
   monitored again; if the student says “clear” or “yes” we resume the slide audio
   where it left off. Any other utterance during the confirming state is treated as
   a follow‑up question (the same buffering/timeout logic applies), triggering a
   simplified lay‑person explanation.
5. **Fallbacks.** If no transcript arrives within ~10 seconds of entering listening
   mode the audio automatically resumes so the session doesn’t hang.

This pattern ensures natural, real‑time interaction while avoiding loops caused by
the teacher’s own TTS being picked up by the recognizer. The script text is also
compared to each transcript to filter out leakage.

```javascript
const ws = new WebSocket(`ws://localhost:8000/realtime/${sessionId}/ws`);
const chunks = [];

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'audio_chunk') {
    chunks.push(msg.audio_chunk);
    updateProgressUI(chunks.length);
  } else if (msg.type === 'audio_stream_end') {
    playAccumulatedChunks(chunks);
  }
};
```

**Pros:** Best UX for streaming, real-time feedback
**Cons:** More complex implementation

---

### Pattern 4: Synchronized Highlighting
Use `point_timings` to highlight text as audio plays.

```javascript
class Highlighter {
  updateHighlight(currentTimeMs) {
    const active = slide.point_timings.find(
      t => currentTimeMs >= t.start_ms && currentTimeMs < t.end_ms
    );
    highlightElement(active?.point_index);
  }
}
```

**Pros:** Professional UI, helps students follow along
**Cons:** Requires accurate point_timings

## Configuration Options

### Voice Selection

In `app/services/audio_service.py`:

```python
await convert_scripts_to_audio(
    scripts,
    voice_name="en-US-Neural2-A",  # Change voice
    language_code="en-US",          # Change language
    # speak_rate=1.2                # Speed (0.5-2.0)
)
```

**Available US Voices:**
- `en-US-Neural2-A` (Female)
- `en-US-Neural2-G` (Male)
- And 6 more variants...

See `AUDIO_SETUP_GUIDE.md` for all available voices.

## Error Handling

### Google Cloud Credentials Not Set
```
RuntimeError: GOOGLE_APPLICATION_CREDENTIALS environment variable not set
```

**Fix:** Set environment variable before starting server
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
```

### Insufficient Permissions
```
google.api_core.exceptions.PermissionDenied: Permission 'tts.googleapis.com/synthesizeSpeech' denied
```

**Fix:** Add "Cloud Text-to-Speech API User" role to service account in IAM

### Network Issues
```
google.api_core.exceptions.ServiceUnavailable
```

**Fix:** Check internet connection, verify API is enabled in Google Cloud Console

## Performance Tuning

### Reduce Session Creation Time
Instead of generating audio during session creation, stream on-demand:

```python
# Modify session.py to skip audio generation
# Keep audio_data and audio_chunks as None
# Clients request audio when needed via /audio endpoints
```

### Reduce Chunk Size for Faster Streaming
```python
await convert_scripts_to_audio(
    scripts,
    chunk_size=2048  # Default 4096, smaller = more frequent updates
)
```

### Cache Audio Files
Store generated audio to disk instead of regenerating:

```python
import hashlib
import os

cache_dir = "audio_cache"
key = hashlib.md5(script.encode()).hexdigest()
cache_path = f"{cache_dir}/{key}.mp3"

if os.path.exists(cache_path):
    with open(cache_path, 'rb') as f:
        audio_bytes = f.read()
else:
    audio_bytes = await synthesize(script)
    with open(cache_path, 'wb') as f:
        f.write(audio_bytes)
```

## Testing

### Test Text-to-Speech
```python
import asyncio
from app.services.audio_service import convert_text_to_speech

result = asyncio.run(convert_text_to_speech(
    "This is a test of the text to speech system"
))
print(f"Generated {len(result)} bytes of audio")
```

### Test API Endpoint
```bash
# Create session
curl -X POST http://localhost:8000/sessions \
  -F "file=@notes.txt" \
  -o session.json

# Stream audio for slide 0
curl http://localhost:8000/sessions/SESSION_ID/slides/0/audio \
  -o slide.mp3

# Play with: ffplay slide.mp3 or any media player
```

### Test WebSocket
```javascript
const ws = new WebSocket('ws://localhost:8000/realtime/SESSION_ID/ws');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

## Debugging Tips

1. **Check Audio Generation**
   - Look for server logs during session creation
   - Verify Google Cloud credentials in environment

2. **Check WebSocket Connection**
   - Open browser DevTools > Network > WS
   - Look for successful connection and messages

3. **Check Audio Quality**
   - Download audio file and inspect with media player
   - Try different voice options

4. **Monitor Resource Usage**
   - TTS API calls count toward quota
   - Each 1000 characters ≈ $4/million in Google Cloud pricing

## Next Steps

1. Set up Google Cloud credentials (see AUDIO_SETUP_GUIDE.md)
2. Install dependencies: `pip install -r requirements.txt`
3. Start the server: `python main.py`
4. Test audio generation by creating a session
5. Integrate client code using one of the patterns above
6. Customize voice and language as needed

## References

- Full Setup Guide: `AUDIO_SETUP_GUIDE.md`
- Client Examples: `AUDIO_CLIENT_EXAMPLES.js`
- Audio Service Code: `app/services/audio_service.py`
- Google Cloud TTS Docs: https://cloud.google.com/text-to-speech/docs
