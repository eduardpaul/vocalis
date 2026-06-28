# node-red-contrib-vocalis

Custom Node-RED nodes to integrate seamlessly with the **Vocalis Voice Assistant I/O Engine**.

This package provides a drag-and-drop suite of nodes to speak, ask questions, identify speakers, and trigger automations on wake word detection. By routing all hardware audio streams through a unified Python daemon, this package prevents audio driver conflicts and allows multiple flows to interact with the same microphone/speaker safely.

---

## Installation

To install this package locally in your Node-RED instance:

1. Locate your Node-RED user directory (typically `~/.node-red` or `C:\Users\<username>\.node-red`).
2. Run npm install pointing to the directory containing this package:
   ```bash
   cd ~/.node-red
   npm install /path/to/voice_clean/node-red-contrib-vocalis
   ```
3. Restart Node-RED. The **Vocalis Voice** section will appear in your palette.

---

## Available Nodes

### 1. `vocalis config` (Configuration Node)
Stores connection settings for the Vocalis Python daemon.
* **Host**: IP address or hostname of the daemon (e.g. `localhost`).
* **Port**: Port of the FastAPI server (default: `8080`).
* **SSL/TLS**: Enable if the Vocalis server is hosted behind a secure proxy.
* **WebSocket**: Automatically connects to `ws://<host>:<port>/ws` and manages automatic reconnection.

### 2. `vocalis say`
Plays synthesized Text-To-Speech (TTS) audio out loud through the system speaker.
* **TTS Text**: The message to synthesize (can also be passed dynamically in `msg.payload`).
* **Output**: Sends a message when playback finishes, allowing you to sequence actions.

### 3. `vocalis ask`
An interactive prompt-and-capture node. Plays a TTS prompt, then records and transcribes the user's voice command.
* **Prompt Text**: Greeting spoken before listening (can also be passed dynamically in `msg.payload`).
* **Barge-In**: If enabled, the user can interrupt the prompt by speaking immediately.
* **Verify Speaker**: If enabled, runs biometric voice verification to check the speaker's identity.
* **Outputs**:
  * **Output 1 (Success)**: Emits if speech is successfully captured and verified.
    * `msg.transcription`: The transcribed text.
    * `msg.speaker`: The verified speaker's name.
    * `msg.audio_wav_base64`: The captured audio as a WAV base64 string.
  * **Output 2 (Timeout / Failed)**: Emits if VAD times out (silence) or speaker verification fails.

### 4. `vocalis wake` (Wake Word Trigger)
A real-time listener node that triggers when the background wakeword detection loop hears the wake word (e.g., *"Alfred"* or *"Hey Bro"*).
* **Outputs**:
  * **Output 1 (Wake Event)**: Emits immediately when the wake word is heard. Perfect for turning down TV volume or flashing visual indicators.
    * `msg.payload`: `{ event: "wake_detected", model: "alfred", score: 0.89 }`
  * **Output 2 (Command Captured)**: Emits once the user finishes speaking their command (if `auto_ask` is enabled on the server).
    * `msg.transcription`: Decoded voice command.
    * `msg.speaker`: Verified speaker name.
