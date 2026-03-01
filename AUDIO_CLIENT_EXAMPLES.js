/**
 * Real-Time Audio Streaming Client
 * 
 * This example demonstrates how to integrate the text-to-speech audio feature
 * with your frontend application. It includes both REST and WebSocket approaches.
 */

// ============================================================================
// APPROACH 1: Simple Audio Playback with Session Audio Data
// ============================================================================

class SimpleAudioPlayer {
  constructor(sessionId) {
    this.sessionId = sessionId;
  }

  /**
   * Play audio for a slide from pre-generated audio data
   * Use this when you already have the session data with audio_data field
   */
  async playSlideAudio(slide) {
    if (!slide.audio_data) {
      console.warn("No audio data available for this slide");
      return;
    }

    try {
      // Decode base64 audio data
      const binaryString = atob(slide.audio_data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      // Create blob and audio URL
      const blob = new Blob([bytes], { type: "audio/mpeg" });
      const url = URL.createObjectURL(blob);

      // Play audio
      const audio = new Audio(url);
      audio.play();

      return audio;
    } catch (error) {
      console.error("Error playing audio:", error);
    }
  }
}

// Usage:
// const player = new SimpleAudioPlayer("session-id");
// player.playSlideAudio(slide);

// ============================================================================
// APPROACH 2: Streaming Audio with REST API
// ============================================================================

class StreamingAudioPlayer {
  constructor(sessionId) {
    this.sessionId = sessionId;
    this.currentAudio = null;
  }

  /**
   * Stream audio directly from the REST API endpoint
   * Best for large audio files or reducing initial session response time
   */
  async streamSlideAudio(slideId) {
    try {
      const response = await fetch(
        `/sessions/${this.sessionId}/slides/${slideId}/audio`
      );

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // Create a blob from the audio stream
      const audioBlob = await response.blob();
      const audioUrl = URL.createObjectURL(audioBlob);

      // Play the audio
      this.currentAudio = new Audio(audioUrl);
      this.currentAudio.play();

      return this.currentAudio;
    } catch (error) {
      console.error("Error streaming audio:", error);
    }
  }

  /**
   * Stop audio playback
   */
  stop() {
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.currentTime = 0;
    }
  }
}

// Usage:
// const player = new StreamingAudioPlayer("session-id");
// await player.streamSlideAudio(0);
// player.stop();

// ============================================================================
// APPROACH 3: Real-Time WebSocket Audio Streaming
// ============================================================================

class RealtimeAudioStreamer {
  constructor(sessionId) {
    this.sessionId = sessionId;
    this.ws = null;
    this.audioBuffer = {};
    this.audioContexts = {};
    this.currentSlideId = null;
  }

  /**
   * Connect to WebSocket and set up event handlers
   */
  connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(`ws://localhost:8000/realtime/${this.sessionId}/ws`);

      this.ws.onopen = () => {
        console.log("Connected to realtime audio stream");
        resolve();
      };

      this.ws.onmessage = (event) => {
        this.handleMessage(JSON.parse(event.data));
      };

      this.ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        reject(error);
      };

      this.ws.onclose = () => {
        console.log("Disconnected from realtime audio stream");
      };
    });
  }

  /**
   * Handle incoming WebSocket messages
   */
  handleMessage(message) {
    switch (message.type) {
      case "audio_stream_start":
        this.onAudioStreamStart(message.slide_id);
        break;

      case "audio_chunk":
        this.onAudioChunk(message.slide_id, message.audio_chunk);
        break;

      case "audio_stream_end":
        this.onAudioStreamEnd(message.slide_id);
        break;

      default:
        console.log("Received message:", message);
    }
  }

  /**
   * Called when audio stream for a slide starts
   */
  onAudioStreamStart(slideId) {
    console.log(`Audio stream started for slide ${slideId}`);
    this.currentSlideId = slideId;
    this.audioBuffer[slideId] = [];
  }

  /**
   * Accumulate audio chunks as they arrive
   */
  onAudioChunk(slideId, chunkData) {
    if (!this.audioBuffer[slideId]) {
      this.audioBuffer[slideId] = [];
    }
    this.audioBuffer[slideId].push(chunkData);
    console.log(`Received audio chunk ${this.audioBuffer[slideId].length} for slide ${slideId}`);
  }

  /**
   * When stream ends, combine chunks and play audio
   */
  onAudioStreamEnd(slideId) {
    console.log(`Audio stream ended for slide ${slideId}`);
    
    if (this.audioBuffer[slideId] && this.audioBuffer[slideId].length > 0) {
      const fullAudio = this.audioBuffer[slideId].join("");
      this.playAudioFromBase64(fullAudio, slideId);
    }
  }

  /**
   * Convert base64 audio data to blob and play
   */
  playAudioFromBase64(base64String, slideId) {
    try {
      // Decode base64
      const binaryString = atob(base64String);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      // Create blob and play
      const blob = new Blob([bytes], { type: "audio/mpeg" });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.play();

      console.log(`Now playing audio for slide ${slideId}`);
    } catch (error) {
      console.error("Error playing audio from base64:", error);
    }
  }

  /**
   * Close the WebSocket connection
   */
  disconnect() {
    if (this.ws) {
      this.ws.close();
    }
  }
}

// Usage:
// const streamer = new RealtimeAudioStreamer("session-id");
// await streamer.connect();
// // Listen for audio streams via WebSocket
// streamer.disconnect();

// ============================================================================
// APPROACH 4: Audio UI Component (React Example)
// ============================================================================

/*
import React, { useState, useEffect } from 'react';

const AudioSlidePlayer = ({ session, slideIndex }) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioPlayer, setAudioPlayer] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const player = new StreamingAudioPlayer(session.id);
    setAudioPlayer(player);

    return () => {
      if (player.currentAudio) {
        player.stop();
      }
    };
  }, [session.id]);

  const handlePlayAudio = async () => {
    try {
      setError(null);
      setIsPlaying(true);
      
      const audio = await audioPlayer.streamSlideAudio(slideIndex);
      
      if (audio) {
        audio.onended = () => setIsPlaying(false);
      }
    } catch (err) {
      setError(err.message);
      setIsPlaying(false);
    }
  };

  const handleStop = () => {
    audioPlayer.stop();
    setIsPlaying(false);
  };

  return (
    <div className="audio-player">
      <button 
        onClick={handlePlayAudio}
        disabled={isPlaying}
      >
        {isPlaying ? "Playing..." : "Play Audio"}
      </button>
      
      {isPlaying && (
        <button onClick={handleStop}>Stop</button>
      )}
      
      {error && <div className="error">{error}</div>}
    </div>
  );
};

export default AudioSlidePlayer;
*/

// ============================================================================
// APPROACH 5: Advanced - Synchronized Highlighting
// ============================================================================

class SynchronizedAudioHighlighter {
  constructor(sessionId, slideElement) {
    this.sessionId = sessionId;
    this.slideElement = slideElement;
    this.currentAudio = null;
    this.pointTimings = [];
  }

  /**
   * Play audio and highlight points as they're spoken
   * Requires slide.point_timings to be populated
   */
  async playWithHighlighting(slide) {
    try {
      // Store timings for synchronization
      this.pointTimings = slide.point_timings || [];

      // Create audio element
      const binaryString = atob(slide.audio_data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      const blob = new Blob([bytes], { type: "audio/mpeg" });
      const url = URL.createObjectURL(blob);
      this.currentAudio = new Audio(url);

      // Set up highlighting based on timing
      this.currentAudio.addEventListener("timeupdate", () => {
        this.updateHighlight(this.currentAudio.currentTime * 1000);
      });

      this.currentAudio.play();
    } catch (error) {
      console.error("Error playing audio with highlighting:", error);
    }
  }

  /**
   * Update which point is highlighted based on current playback time
   */
  updateHighlight(currentTimeMs) {
    // Find which point should be highlighted
    const activePoint = this.pointTimings.find(
      (timing) =>
        currentTimeMs >= timing.start_ms && currentTimeMs < timing.end_ms
    );

    // Remove all previous highlights
    this.slideElement.querySelectorAll(".point").forEach((el) => {
      el.classList.remove("speaking");
    });

    // Highlight the active point
    if (activePoint !== undefined) {
      const pointElement = this.slideElement.querySelector(
        `.point[data-index="${activePoint.point_index}"]`
      );
      if (pointElement) {
        pointElement.classList.add("speaking");
      }
    }
  }

  /**
   * Stop playback and clear highlighting
   */
  stop() {
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.currentTime = 0;
    }

    this.slideElement.querySelectorAll(".point").forEach((el) => {
      el.classList.remove("speaking");
    });
  }
}

// Usage with HTML:
// <div id="slide">
//   <div class="point" data-index="0">Point 1</div>
//   <div class="point" data-index="1">Point 2</div>
// </div>
//
// const highlighter = new SynchronizedAudioHighlighter(
//   "session-id",
//   document.getElementById("slide")
// );
// highlighter.playWithHighlighting(slide);

// ============================================================================
// CSS for Highlighting
// ============================================================================

/*
.point {
  padding: 10px;
  margin: 5px 0;
  border-radius: 4px;
  transition: background-color 0.2s;
}

.point.speaking {
  background-color: #fff3cd;
  border: 2px solid #ff9800;
  box-shadow: 0 0 8px rgba(255, 152, 0, 0.3);
}
*/

// Export all classes
export {
  SimpleAudioPlayer,
  StreamingAudioPlayer,
  RealtimeAudioStreamer,
  SynchronizedAudioHighlighter,
};
