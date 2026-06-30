# Vocalis Voice Assistant I/O Engine (v1.1.0)

*Vocalis* is an event-driven Voice Assistant I/O Engine implementing a single-orchestrator, thread-isolated worker topology. It handles low-level edge hardware operations (VAD, ASR, TTS, Speaker Identification) and exposes them through multiplexed HTTP and MQTT interfaces.

---

## Prerequisites
* **Operating System**: Linux (ARM64/x86_64, e.g., Raspberry Pi 5) or Windows (10/11)
* **Python**: Version 3.11+
* **Audio Hardware**: Microphone and Speaker (or configured loopback devices)

---

## Task 1: Setup and Installation

### 1. Initialize Virtual Environment and Install Dependencies
From the project root directory, initialize the environment and install packages:
```bash
# Create the virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

*Note: install openwakeword without deps make it work 'pip install openwakeword --no-deps'.*


### 2. Download ML Models
Ensure the required ONNX models are present. Run the downloader helper to fetch the CAM++ speaker ID model:
```bash
python scripts/download_models.py
```

*Note: Ensure that `silero_vad.onnx`, `sherpa-onnx-moonshine-base-es-quantized-2026-02-27/` and `sherpa-onnx-supertonic-3-tts-int8-2026-05-11/` directories are located inside the `./models/` folder.*

---

## Task 2: Configuration

Modify **`config.yaml`** at the root of the project to customize device indices, broker settings, and voice recognition parameters:

```yaml
system:
  name: "living_room_node"
  log_level: "INFO"
  max_concurrency_wait: 5.0 # Seconds to wait for IDLE before 409 Conflict

interfaces:
  http:
    host: "0.0.0.0"
    port: 8080
  mqtt:
    enabled: true
    broker: "localhost"
    port: 1883
    topic_prefix: "home/assistant/node1"

audio:
  input_device_index: "default"
  output_device_index: "default"
  sample_rate: 16000
  channels: 1
  chunk_size: 512
```

---

## Task 3: Running the Application

Start the Vocalis service:
```bash
python -m vocalis.main
```
This loads your `config.yaml`, binds the audio hardware drivers, launches the FastAPI server (HTTP) on port `8080`, and connects to the background MQTT broker.

---

## Task 4: Interacting with the Engine

### Option A: HTTP REST API
* **Ask Execution**: Send an `/ask` post request to the HTTP engine:
  ```bash
  curl -X POST http://localhost:8080/ask \
    -H "Content-Type: application/json" \
    -d '{
      "context_id": "req_101",
      "tts_text": "Buenos días, ¿en qué puedo ayudarte?",
      "barge_in": true,
      "require_speaker_id": true,
      "output_format": "both"
    }'
  ```

* **Say Out Loud (TTS only)**: Send a `/say` post request to play back synthesized audio text:
  ```bash
  curl -X POST http://localhost:8080/say \
    -H "Content-Type: application/json" \
    -d '{
      "context_id": "req_102",
      "text": "Hola, esto es un anuncio de voz."
    }'
  ```

* **System Status**: Get current state manager state:
  ```bash
  curl http://localhost:8080/status
  ```

### Option B: MQTT Topics
* **Request ask execution**: Publish a JSON payload to `home/assistant/node1/ask/request` matching the `AskRequest` structure.
* **Listen for ask results**: Subscribe to `home/assistant/node1/ask/result`.
* **Request say execution**: Publish a JSON payload to `home/assistant/node1/say/request` matching the `SayRequest` structure (e.g. `{"context_id": "req_102", "text": "Hola"}`).
* **Listen for say results**: Subscribe to `home/assistant/node1/say/result` (returns a `SayResponse` e.g. `{"context_id": "req_102", "status": "success"}`).
* **Track state changes**: Subscribe to `home/assistant/node1/state`.

---

## Task 5: Standby Wakeword Service

You can run Vocalis in standby wakeword detection mode. This keeps the microphone active, analyzing audio using `openWakeWord` (defaulting to the `openwakeword_hey_bro.onnx` model). When the wake word is detected, it triggers the Vocalis Ask pipeline with a randomized Spanish prompt.

*Note: Wake word ONNX models (like `openwakeword_alfred.onnx` or `openwakeword_hey_bro.onnx`) are placed inside the `models/` directory.*

```bash
# Start with default (hey_bro)
python scripts/run_wakeword.py

# Or start with a specific model (e.g. alfred)
python scripts/run_wakeword.py --model openwakeword_alfred.onnx
```

* **Interactive Prompts**: Spanish wake responses (e.g., `"¿Qué desea?"`, `"¿Cómo puedo ayudar?"`, `"Sí, mi señor"`) are randomly selected, played via TTS, and the engine automatically captures your command and performs speaker verification.

---

## Task 6: Running the Test Suite

Execute the automated pytest suite using the real models:
```bash
python -m pytest -v
```
This tests configurations, StateManager locks, VAD capture, Moonshine ASR decodes, Supertonic synthesis, speaker verification (CAM++), and the active challenge loop flow.


RASBERY NOTES: 

nano ~/.bashrc
export PA_ALSA_PLUGHW=1

nano ~/.asoundrc
pcm.!default {
    type asym
    capture.pcm "plug:hw:2,0"
}
