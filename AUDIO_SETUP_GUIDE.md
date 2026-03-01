## Text-to-Speech Audio Feature Setup Guide

This document explains how to set up and use the new text-to-speech audio generation feature that converts slide scripts to audio in real-time.

### Overview

The audio feature automatically converts all slide scripts into natural-sounding audio using Google Cloud Text-to-Speech API. Audio is generated when you create a session and is included in the response, allowing real-time playback.

### Prerequisites

1. **Google Cloud Project**: You need a Google Cloud project with the Text-to-Speech API enabled.
2. **Service Account**: Create a service account with Text-to-Speech permissions.
3. **Credentials File**: Download the service account JSON file.

### Setup Instructions

#### 1. Enable Google Cloud Text-to-Speech API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Text-to-Speech API:
   - Go to "APIs & Services" > "Library"
   - Search for "Text-to-Speech API"
   - Click "Enable"

#### 2. Create a Service Account

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Fill in the service account details and click "Create and Continue"
4. Grant the "Cloud Text-to-Speech API User" role
5. Click "Continue" and then "Done"

#### 3. Create and Download the Service Account Key

1. Go to "APIs & Services" > "Credentials"
2. Click on the service account you just created
3. Go to the "Keys" tab
4. Click "Add Key" > "Create new key"
5. Choose "JSON" and click "Create"
6. The JSON file will download automatically

#### 4. Set Up Environment Variable

Place your Google Cloud service account JSON file in a secure location and set the environment variable:

**On Windows (Command Prompt):**
```cmd
set GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\your\service-account-key.json
```

**On Windows (PowerShell):**
```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\your\service-account-key.json"
```

**On Linux/macOS:**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account-key.json"
```

#### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

The new `google-cloud-texttospeech` and `pydub` packages will be installed automatically.

### API Endpoints

#### 1. Create Session with Audio

**POST** `/sessions`

When you create a new session by uploading notes, audio is automatically generated for all slide scripts.

**Request:**
```
Content-Type: multipart/form-data
file: <your notes file>
```

**Response:**
Returns a `SessionState` object including each slide with:
- `audio_data`: Full MP3 audio as base64
- `audio_chunks`: Pre-split audio chunks for streaming (base64)

#### 2. Stream Slide Audio (MP3)

**GET** `/sessions/{session_id}/slides/{slide_id}/audio`

Streams the MP3 audio file for a specific slide.

**Response:**
- Content-Type: `audio/mpeg`
- Raw MP3 audio stream

**Example (Client):**
```javascript
const response = await fetch(`/sessions/{sessionId}/slides/{slideId}/audio`);
const audioBlob = await response.blob();
const url = URL.createObjectURL(audioBlob);
const audio = new Audio(url);
audio.play();
```

#### 3. Get Audio Chunks via REST

**GET** `/sessions/{session_id}/slides/{slide_id}/audio/base64`

Returns pre-split audio chunks as base64 strings for WebSocket transmission or batch processing.

**Response:**
```json
{
  "slide_id": 0,
  "audio_chunks": ["base64_chunk_1", "base64_chunk_2", ...],
  "chunk_count": 42
}
```

### WebSocket Real-Time Audio Streaming

Connect to the WebSocket endpoint to receive real-time audio stream updates:

**WebSocket** `/realtime/{session_id}/ws`

#### Message Types

**1. Audio Stream Start**
```json
{
  "type": "audio_stream_start",
  "slide_id": 0
}
```

**2. Audio Chunk (Real-time)**
```json
{
  "type": "audio_chunk",
  "slide_id": 0,
  "audio_chunk": "base64_encoded_audio_data"
}
```

**3. Audio Stream End**
```json
{
  "type": "audio_stream_end",
  "slide_id": 0
}
```

#### Client Example (JavaScript)

```javascript
const sessionId = "your-session-id";
const ws = new WebSocket(`ws://localhost:8000/realtime/${sessionId}/ws`);

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  
  if (message.type === "audio_stream_start") {
    console.log(`Starting audio for slide ${message.slide_id}`);
    audioBuffer = [];
  } else if (message.type === "audio_chunk") {
    // Accumulate chunks
    audioBuffer.push(message.audio_chunk);
  } else if (message.type === "audio_stream_end") {
    // Combine chunks and play
    const fullAudio = audioBuffer.join("");
    playAudioFromBase64(fullAudio, message.slide_id);
  }
};

function playAudioFromBase64(base64String, slideId) {
  const binaryString = atob(base64String);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: "audio/mpeg" });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.play();
}
```

### Customization

The audio generation can be customized in the `convert_scripts_to_audio()` function:

#### Available Voices

**English (US):**
- `en-US-Neural2-A` (Female) - Default
- `en-US-Neural2-C` (Female)
- `en-US-Neural2-E` (Female)
- `en-US-Neural2-F` (Female)
- `en-US-Neural2-G` (Male)
- `en-US-Neural2-H` (Male)
- `en-US-Neural2-I` (Male)
- `en-US-Neural2-J` (Male)

**English (UK):**
- `en-GB-Neural2-A` (Female)
- `en-GB-Neural2-B` (Male)
- And others...

#### Example: Change Voice and Speed

In `app/api/routes/session.py`, modify the `convert_scripts_to_audio()` call:

```python
audio_results = await convert_scripts_to_audio(
    scripts,
    language_code="en-US",
    voice_name="en-US-Neural2-G",  # Male voice
    # Note: speak_rate parameter can also be added (0.5 to 2.0)
)
```

### Troubleshooting

#### 1. `GOOGLE_APPLICATION_CREDENTIALS not set`
Make sure the environment variable is set to the correct path before starting the server.

```bash
# Verify it's set
echo $GOOGLE_APPLICATION_CREDENTIALS  # Linux/macOS
echo %GOOGLE_APPLICATION_CREDENTIALS%  # Windows Command Prompt
```

#### 2. `Permission denied` / `Insufficient IAM Permissions`
Ensure the service account has the "Cloud Text-to-Speech API User" role in IAM.

#### 3. Audio Generation is Slow
- Google Cloud TTS usually takes 1-3 seconds per slide
- Slow generation is normal for the first request as Google initializes connections
- Subsequent requests are faster
- Consider using a frontend loading indicator while audio is generating

#### 4. WebSocket Audio Chunks Not Received
- Verify the WebSocket connection is established
- Check the server logs for connection errors
- Ensure the `broadcast_audio_chunk()` function is being called

### Performance Notes

- **Audio Generation**: ~1-3 seconds per slide (varies by script length)
- **Chunk Size**: Default 4096 bytes (configurable)
- **Streaming**: Real-time chunks are sent as soon as they're generated
- **Caching**: Audio is pre-generated and cached in memory during session creation

### Future Enhancements

Potential improvements for the audio system:

1. **Custom Pronunciation**: Dictionary-based pronunciation customization
2. **Audio Effects**: Add background music or sound effects
3. **Multiple Languages**: Support for multilingual presentations
4. **Voice Cloning**: Custom voice synthesis
5. **Audio Caching**: Persistent storage of generated audio files
6. **Synchronization**: Advanced timing sync with slide animations

### Support

For issues with Google Cloud:
- [Google Cloud Text-to-Speech Documentation](https://cloud.google.com/text-to-speech/docs)
- [Google Cloud Support](https://cloud.google.com/support)

For issues with this implementation:
- Check server logs for detailed error messages
- Verify all environment variables are set correctly
- Ensure Google Cloud projects and APIs are properly configured
