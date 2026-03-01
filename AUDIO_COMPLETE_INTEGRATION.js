/**
 * Complete Audio Integration Example
 * 
 * This example shows how to integrate the text-to-speech feature
 * into a complete teaching session application.
 */

// ============================================================================
// Configuration
// ============================================================================

const CONFIG = {
  API_BASE: "http://localhost:8000",
  WS_BASE: "ws://localhost:8000",
  DEFAULT_VOICE: "en-US-Neural2-A",
  DEFAULT_LANGUAGE: "en-US",
};

// ============================================================================
// Audio Service Class
// ============================================================================

class TeacherAudioService {
  constructor(sessionId) {
    this.sessionId = sessionId;
    this.ws = null;
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    this.audioQueue = {};
    this.isConnected = false;
    this.listeners = {
      onAudioStart: [],
      onAudioProgress: [],
      onAudioEnd: [],
      onError: [],
    };
  }

  /**
   * Connect to WebSocket for real-time audio streaming
   */
  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(`${CONFIG.WS_BASE}/realtime/${this.sessionId}/ws`);

      this.ws.onopen = () => {
        this.isConnected = true;
        console.log("Connected to audio service");
        resolve();
      };

      this.ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          this.handleWebSocketMessage(message);
        } catch (error) {
          console.error("Error parsing WebSocket message:", error);
        }
      };

      this.ws.onerror = (error) => {
        this.isConnected = false;
        console.error("WebSocket error:", error);
        this.emit("onError", error);
        reject(error);
      };

      this.ws.onclose = () => {
        this.isConnected = false;
        console.log("Disconnected from audio service");
      };
    });
  }

  /**
   * Handle messages from WebSocket
   */
  handleWebSocketMessage(message) {
    const { type, slide_id, audio_chunk } = message;

    switch (type) {
      case "audio_stream_start":
        this.audioQueue[slide_id] = [];
        this.emit("onAudioStart", { slideId: slide_id });
        break;

      case "audio_chunk":
        if (!this.audioQueue[slide_id]) {
          this.audioQueue[slide_id] = [];
        }
        this.audioQueue[slide_id].push(audio_chunk);
        this.emit("onAudioProgress", {
          slideId: slide_id,
          chunkCount: this.audioQueue[slide_id].length,
        });
        break;

      case "audio_stream_end":
        this.playQueuedAudio(slide_id);
        this.emit("onAudioEnd", { slideId: slide_id });
        break;
    }
  }

  /**
   * Play audio from accumulated chunks
   */
  playQueuedAudio(slideId) {
    const chunks = this.audioQueue[slideId];
    if (!chunks || chunks.length === 0) {
      console.warn(`No audio chunks for slide ${slideId}`);
      return;
    }

    try {
      // Combine all chunks
      const fullAudio = chunks.join("");

      // Decode base64
      const binaryString = atob(fullAudio);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      // Create and play audio
      const blob = new Blob([bytes], { type: "audio/mpeg" });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);

      audio.onended = () => {
        URL.revokeObjectURL(url);
      };

      audio.play();
    } catch (error) {
      console.error(`Error playing audio for slide ${slideId}:`, error);
      this.emit("onError", error);
    }
  }

  /**
   * Play audio from pre-loaded session data
   */
  playFromSessionData(slide) {
    if (!slide.audio_data) {
      console.warn("No audio data in slide");
      return;
    }

    try {
      const bytes = new Uint8Array(atob(slide.audio_data).split("").map((c) => c.charCodeAt(0)));
      const blob = new Blob([bytes], { type: "audio/mpeg" });
      const audio = new Audio(URL.createObjectURL(blob));
      audio.play();
      return audio;
    } catch (error) {
      console.error("Error playing audio:", error);
      this.emit("onError", error);
    }
  }

  /**
   * Stream audio directly from API (on-demand)
   */
  async streamFromAPI(slideId) {
    try {
      const response = await fetch(
        `${CONFIG.API_BASE}/sessions/${this.sessionId}/slides/${slideId}/audio`
      );

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const blob = await response.blob();
      const audio = new Audio(URL.createObjectURL(blob));
      audio.play();
      return audio;
    } catch (error) {
      console.error("Error streaming audio:", error);
      this.emit("onError", error);
    }
  }

  /**
   * Add event listener
   */
  on(eventName, callback) {
    if (this.listeners[eventName]) {
      this.listeners[eventName].push(callback);
    }
  }

  /**
   * Emit event to all listeners
   */
  emit(eventName, data) {
    if (this.listeners[eventName]) {
      this.listeners[eventName].forEach((callback) => callback(data));
    }
  }

  /**
   * Disconnect WebSocket
   */
  disconnect() {
    if (this.ws) {
      this.ws.close();
    }
  }
}

// ============================================================================
// Teaching Session Manager
// ============================================================================

class TeachingSessionManager {
  constructor() {
    this.session = null;
    this.currentSlideIndex = 0;
    this.audioService = null;
    this.isAudioEnabled = true;
  }

  /**
   * Create a new teaching session from notes file
   */
  async createSession(file) {
    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(`${CONFIG.API_BASE}/sessions`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      this.session = await response.json();
      console.log(`Session created: ${this.session.id}`);

      // Initialize audio service
      this.audioService = new TeacherAudioService(this.session.id);

      return this.session;
    } catch (error) {
      console.error("Error creating session:", error);
      throw error;
    }
  }

  /**
   * Connect to real-time audio service
   */
  async connectAudio() {
    if (!this.audioService) {
      throw new Error("Session not initialized");
    }

    await this.audioService.connect();

    // Set up audio event listeners
    this.audioService.on("onAudioStart", ({ slideId }) => {
      console.log(`Audio started for slide ${slideId}`);
      this.onAudioStart?.(slideId);
    });

    this.audioService.on("onAudioProgress", ({ slideId, chunkCount }) => {
      console.log(`Received ${chunkCount} chunks for slide ${slideId}`);
      this.onAudioProgress?.(slideId, chunkCount);
    });

    this.audioService.on("onAudioEnd", ({ slideId }) => {
      console.log(`Audio ended for slide ${slideId}`);
      this.onAudioEnd?.(slideId);
    });

    this.audioService.on("onError", (error) => {
      console.error("Audio error:", error);
      this.onAudioError?.(error);
    });
  }

  /**
   * Get current slide
   */
  getCurrentSlide() {
    if (!this.session) return null;
    return this.session.slides[this.currentSlideIndex];
  }

  /**
   * Go to next slide
   */
  nextSlide() {
    if (this.currentSlideIndex < this.session.slides.length - 1) {
      this.currentSlideIndex++;
      return this.getCurrentSlide();
    }
    return null;
  }

  /**
   * Go to previous slide
   */
  previousSlide() {
    if (this.currentSlideIndex > 0) {
      this.currentSlideIndex--;
      return this.getCurrentSlide();
    }
    return null;
  }

  /**
   * Jump to specific slide
   */
  goToSlide(slideIndex) {
    if (slideIndex >= 0 && slideIndex < this.session.slides.length) {
      this.currentSlideIndex = slideIndex;
      return this.getCurrentSlide();
    }
    return null;
  }

  /**
   * Play audio for current slide
   */
  playCurrentAudio() {
    if (!this.isAudioEnabled || !this.audioService) {
      console.warn("Audio is disabled");
      return;
    }

    const slide = this.getCurrentSlide();
    if (!slide) return;

    // Use pre-loaded audio data if available
    if (slide.audio_data) {
      this.audioService.playFromSessionData(slide);
    } else {
      // Otherwise stream from API
      this.audioService.streamFromAPI(this.currentSlideIndex);
    }
  }

  /**
   * Stop audio playback
   */
  stopAudio() {
    const audio = document.querySelector("audio");
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }
  }

  /**
   * Toggle audio on/off
   */
  toggleAudio() {
    this.isAudioEnabled = !this.isAudioEnabled;
    if (!this.isAudioEnabled) {
      this.stopAudio();
    }
    return this.isAudioEnabled;
  }

  /**
   * Ask a question during the session
   */
  async askQuestion(questionText, slideIndex = null) {
    if (!this.session) throw new Error("Session not initialized");

    const payload = {
      question: questionText,
      slide_index: slideIndex ?? this.currentSlideIndex,
    };

    const response = await fetch(
      `${CONFIG.API_BASE}/sessions/${this.session.id}/question`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const answer = await response.json();
    console.log("Answer:", answer);
    return answer;
  }

  /**
   * Disconnect audio service
   */
  disconnect() {
    if (this.audioService) {
      this.audioService.disconnect();
    }
  }
}

// ============================================================================
// UI Components (Vanilla JS Example)
// ============================================================================

class TeachingUI {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.manager = new TeachingSessionManager();
    this.setupEventListeners();
  }

  setupEventListeners() {
    // File upload
    const fileInput = document.querySelector("#notes-file");
    fileInput?.addEventListener("change", (e) => this.handleFileUpload(e));

    // Navigation buttons
    document.querySelector("#prev-btn")?.addEventListener("click", () => this.previousSlide());
    document.querySelector("#next-btn")?.addEventListener("click", () => this.nextSlide());

    // Audio controls
    document.querySelector("#play-audio-btn")?.addEventListener("click", () => this.playAudio());
    document.querySelector("#stop-audio-btn")?.addEventListener("click", () => this.stopAudio());
    document.querySelector("#toggle-audio-btn")?.addEventListener("click", () => this.toggleAudio());

    // Session events
    this.manager.onAudioStart = (slideId) => {
      this.updateStatus(`Audio playing for slide ${slideId}...`);
      this.updateUI();
    };

    this.manager.onAudioProgress = (slideId, chunkCount) => {
      this.updateStatus(`Buffering... (${chunkCount} chunks received)`);
    };

    this.manager.onAudioEnd = (slideId) => {
      this.updateStatus("Audio finished");
    };

    this.manager.onAudioError = (error) => {
      this.updateStatus(`Error: ${error.message}`, "error");
    };
  }

  async handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    try {
      this.updateStatus("Creating session...");
      await this.manager.createSession(file);

      this.updateStatus("Connecting to audio service...");
      await this.manager.connectAudio();

      this.updateStatus("Ready to teach!");
      this.updateUI();
    } catch (error) {
      this.updateStatus(`Error: ${error.message}`, "error");
    }
  }

  updateUI() {
    const slide = this.manager.getCurrentSlide();
    if (!slide) return;

    // Update slide display
    const slideContent = document.querySelector("#slide-content");
    if (slideContent) {
      slideContent.innerHTML = `
        <h2>${slide.title}</h2>
        <ul>
          ${slide.points.map((p) => `<li>${p.text}</li>`).join("")}
        </ul>
        <p><strong>Script:</strong> ${slide.script}</p>
      `;
    }

    // Update slide counter
    const counter = document.querySelector("#slide-counter");
    if (counter) {
      counter.textContent = `${this.manager.currentSlideIndex + 1} / ${this.manager.session.slides.length}`;
    }

    // Update button states
    document.querySelector("#prev-btn").disabled = this.manager.currentSlideIndex === 0;
    document.querySelector("#next-btn").disabled =
      this.manager.currentSlideIndex === this.manager.session.slides.length - 1;
  }

  playAudio() {
    this.manager.playCurrentAudio();
  }

  stopAudio() {
    this.manager.stopAudio();
  }

  toggleAudio() {
    const isEnabled = this.manager.toggleAudio();
    const btn = document.querySelector("#toggle-audio-btn");
    if (btn) {
      btn.textContent = isEnabled ? "Disable Audio" : "Enable Audio";
    }
  }

  previousSlide() {
    this.manager.previousSlide();
    this.updateUI();
    this.manager.stopAudio();
  }

  nextSlide() {
    this.manager.nextSlide();
    this.updateUI();
    this.manager.stopAudio();
  }

  updateStatus(message, type = "info") {
    const status = document.querySelector("#status");
    if (status) {
      status.textContent = message;
      status.className = `status ${type}`;
    }
  }
}

// ============================================================================
// HTML Template
// ============================================================================

/*
<!DOCTYPE html>
<html>
<head>
  <title>Teaching Session with Audio</title>
  <style>
    #app {
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
      font-family: Arial, sans-serif;
    }

    #slide-content {
      background: #f5f5f5;
      padding: 20px;
      border-radius: 8px;
      margin: 20px 0;
    }

    .controls {
      display: flex;
      gap: 10px;
      margin: 20px 0;
      flex-wrap: wrap;
    }

    button {
      padding: 10px 20px;
      background: #007bff;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
    }

    button:hover {
      background: #0056b3;
    }

    button:disabled {
      background: #ccc;
      cursor: not-allowed;
    }

    #status {
      padding: 10px;
      border-radius: 4px;
      margin: 10px 0;
    }

    #status.info {
      background: #e7f3ff;
      color: #0066cc;
    }

    #status.error {
      background: #ffe7e7;
      color: #cc0000;
    }

    #slide-counter {
      font-weight: bold;
      margin: 10px 0;
    }
  </style>
</head>
<body>
  <div id="app">
    <h1>Teaching Session Manager</h1>

    <div>
      <input type="file" id="notes-file" accept=".txt,.pdf" />
      <label>Upload your teaching notes (TXT or PDF)</label>
    </div>

    <div id="status">Ready to start</div>
    <div id="slide-counter">0 / 0</div>

    <div id="slide-content">
      No slide loaded yet. Upload a file to get started.
    </div>

    <div class="controls">
      <button id="prev-btn">← Previous</button>
      <button id="play-audio-btn">▶ Play Audio</button>
      <button id="stop-audio-btn">⏹ Stop Audio</button>
      <button id="toggle-audio-btn">🔊 Disable Audio</button>
      <button id="next-btn">Next →</button>
    </div>
  </div>

  <script src="complete-audio-integration.js"></script>
  <script>
    // Initialize UI when page loads
    const ui = new TeachingUI("app");
  </script>
</body>
</html>
*/

// ============================================================================
// Export for module use
// ============================================================================

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    TeacherAudioService,
    TeachingSessionManager,
    TeachingUI,
    CONFIG,
  };
}
