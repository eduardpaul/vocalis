import asyncio
import logging
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from aiomqtt import Client as MqttClient

from vocalis.config import AppConfig
from vocalis.state import StateManager
from vocalis.audio import SoundDeviceAudioSource, SoundDeviceAudioSink, AudioSource, AudioSink
from vocalis.ml_workers import MLWorkerPool
from vocalis.orchestrator import AssistantEngine, AskRequest, AskResponse, SayRequest, SayResponse

logger = logging.getLogger("vocalis.api")

mqtt_queue = asyncio.Queue()

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vocalis Voice Engine | Control Center</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #070a13;
            --card-bg: rgba(16, 22, 38, 0.7);
            --border-glow: rgba(139, 92, 246, 0.2);
            --primary-grad: linear-gradient(135deg, #7c3aed 0%, #2563eb 100%);
            --accent-pink: #db2777;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --state-idle: #10b981;
            --state-speaking: #3b82f6;
            --state-listening: #fbbf24;
            --state-processing: #8b5cf6;
            --state-challenging: #ef4444;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 2rem 1rem;
            background-image: radial-gradient(circle at 15% 15%, rgba(124, 58, 237, 0.08) 0%, transparent 45%),
                              radial-gradient(circle at 85% 85%, rgba(37, 99, 235, 0.08) 0%, transparent 45%);
        }

        .container {
            width: 100%;
            max-width: 800px;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }

        h1 {
            font-size: 1.8rem;
            font-weight: 700;
            background: linear-gradient(to right, #a78bfa, #60a5fa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }

        .status-container {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            background: rgba(255, 255, 255, 0.03);
            padding: 0.4rem 0.8rem;
            border-radius: 99px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .status-badge {
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            padding: 0.2rem 0.6rem;
            border-radius: 99px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 0.3rem;
            transition: all 0.3s ease;
        }

        .status-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background-color: #fff;
        }

        .badge-idle { background-color: rgba(16, 185, 129, 0.1); border: 1px solid var(--state-idle); color: #34d399; }
        .badge-idle .status-dot { background-color: var(--state-idle); }

        .badge-speaking { background-color: rgba(59, 130, 246, 0.1); border: 1px solid var(--state-speaking); color: #60a5fa; }
        .badge-speaking .status-dot { background-color: var(--state-speaking); }

        .badge-listening { 
            background-color: rgba(251, 191, 36, 0.1); 
            border: 1px solid var(--state-listening); 
            color: #fbbf24;
            animation: pulse-glow 1.2s infinite alternate;
        }
        .badge-listening .status-dot { background-color: var(--state-listening); }

        .badge-processing { background-color: rgba(139, 92, 246, 0.1); border: 1px solid var(--state-processing); color: #c084fc; }
        .badge-processing .status-dot { background-color: var(--state-processing); }

        .badge-challenging { 
            background-color: rgba(239, 68, 68, 0.1); 
            border: 1px solid var(--state-challenging); 
            color: #f87171; 
            animation: pulse-glow 1.2s infinite alternate;
        }
        .badge-challenging .status-dot { background-color: var(--state-challenging); }

        @keyframes pulse-glow {
            from { box-shadow: 0 0 5px rgba(251, 191, 36, 0.2); }
            to { box-shadow: 0 0 15px rgba(251, 191, 36, 0.5); }
        }

        .card {
            background: var(--card-bg);
            backdrop-filter: blur(10px);
            border: 1px solid var(--border-glow);
            border-radius: 12px;
            padding: 1.2rem;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .card-title {
            font-size: 1.1rem;
            font-weight: 600;
            color: #c084fc;
        }

        .form-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }

        @media (max-width: 600px) {
            .form-grid {
                grid-template-columns: 1fr;
            }
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
        }

        .form-group.full-width {
            grid-column: span 2;
        }

        @media (max-width: 600px) {
            .form-group.full-width {
                grid-column: span 1;
            }
        }

        .form-group-row {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 0.4rem;
        }

        label {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        input[type="text"], input[type="number"], select, textarea {
            background: rgba(10, 15, 30, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            color: var(--text-main);
            font-family: inherit;
            font-size: 0.9rem;
            padding: 0.6rem;
            outline: none;
            transition: all 0.2s ease;
            width: 100%;
        }

        input[type="text"]:focus, input[type="number"]:focus, select:focus, textarea:focus {
            border-color: #8b5cf6;
            box-shadow: 0 0 0 1px rgba(139, 92, 246, 0.4);
        }

        input[type="checkbox"] {
            width: 16px;
            height: 16px;
            accent-color: #8b5cf6;
            cursor: pointer;
        }

        .btn {
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 600;
            padding: 0.6rem 1.2rem;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
            color: white;
            text-align: center;
            background: var(--primary-grad);
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.2);
            width: 100%;
        }

        .btn:hover {
            opacity: 0.95;
            box-shadow: 0 4px 16px rgba(124, 58, 237, 0.35);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            box-shadow: none;
        }

        .console {
            background: #03050a;
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 0.8rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            min-height: 150px;
            max-height: 250px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
            box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.6);
        }

        .console-line {
            line-height: 1.4;
        }

        .console-line.info { color: #60a5fa; }
        .console-line.success { color: #34d399; }
        .console-line.warning { color: #fbbf24; }
        .console-line.error { color: #f87171; }
        .console-line.timestamp { color: var(--text-muted); font-size: 0.7rem; margin-right: 0.4rem; }

        .audio-player {
            margin-top: 0.3rem;
            height: 30px;
            outline: none;
            background-color: #03050a;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Vocalis Controller center</h1>
            <div class="status-container">
                <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: 500;">Estado:</span>
                <div id="statusBadge" class="status-badge badge-idle">
                    <span class="status-dot"></span>
                    <span id="statusText">Idle</span>
                </div>
            </div>
        </header>

        <div class="card">
            <div class="card-title">Ejecutar Comando (Ask)</div>
            <div class="form-grid">
                <div class="form-group full-width">
                    <label for="ttsText">Texto a sintetizar (TTS)</label>
                    <textarea id="ttsText" placeholder="Escribe el texto a reproducir antes de escuchar...">¿Quién está ahí?</textarea>
                </div>
                <div class="form-group">
                    <label for="contextId">Context ID</label>
                    <input type="text" id="contextId" placeholder="Ej: ctx_123 (Vacío para auto-generar)">
                </div>
                <div class="form-group">
                    <label for="outputFormat">Formato de Salida</label>
                    <select id="outputFormat">
                        <option value="text">Texto (Transcripción)</option>
                        <option value="audio">Audio (WAV Base64)</option>
                        <option value="both" selected>Ambos (Texto + Audio)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="vadTimeout">Timeout VAD (segundos)</label>
                    <input type="number" id="vadTimeout" value="10.0" step="0.5" min="1">
                </div>
                <div class="form-group">
                    <label>Opciones Adicionales</label>
                    <div style="display: flex; gap: 1.5rem;">
                        <div class="form-group-row">
                            <input type="checkbox" id="bargeIn" checked>
                            <label for="bargeIn">Barge-in (Interrupción)</label>
                        </div>
                        <div class="form-group-row">
                            <input type="checkbox" id="requireSpeakerId">
                            <label for="requireSpeakerId">Identificar Hablante</label>
                        </div>
                    </div>
                </div>
            </div>
            <button class="btn" id="askBtn" onclick="executeAsk()">Enviar Request</button>
        </div>

        <div class="card">
            <div class="card-title">Historial de Eventos Center</div>
            <div class="console" id="consolePanel">
                <div class="console-line info"><span class="console-line timestamp">[Conectado]</span>Consola de eventos iniciada.</div>
            </div>
        </div>
    </div>

    <script>
        const statusBadge = document.getElementById('statusBadge');
        const statusText = document.getElementById('statusText');
        const consolePanel = document.getElementById('consolePanel');
        const askBtn = document.getElementById('askBtn');

        function logToConsole(text, type = 'info') {
            const timeStr = new Date().toLocaleTimeString();
            const line = document.createElement('div');
            line.className = `console-line ${type}`;
            line.innerHTML = `<span class="console-line timestamp">[${timeStr}]</span>${text}`;
            consolePanel.appendChild(line);
            consolePanel.scrollTop = consolePanel.scrollHeight;
        }

        async function pollStatus() {
            try {
                const res = await fetch('/status');
                if (!res.ok) return;
                const data = await res.json();
                
                const state = data.state;
                statusText.textContent = state;
                statusBadge.className = `status-badge badge-${state.toLowerCase()}`;
            } catch (e) {
                console.error("Status polling failed:", e);
            }
        }

        async function executeAsk() {
            let contextId = document.getElementById('contextId').value.trim();
            if (!contextId) {
                contextId = 'ctx_' + Math.floor(Math.random() * 100000);
            }
            const ttsText = document.getElementById('ttsText').value.trim();
            const outputFormat = document.getElementById('outputFormat').value;
            const vadTimeout = parseFloat(document.getElementById('vadTimeout').value) || 10.0;
            const bargeIn = document.getElementById('bargeIn').checked;
            const requireSpeakerId = document.getElementById('requireSpeakerId').checked;

            if (!ttsText) {
                alert("Por favor escribe el texto del prompt TTS.");
                return;
            }

            const payload = {
                context_id: contextId,
                tts_text: ttsText,
                barge_in: bargeIn,
                require_speaker_id: requireSpeakerId,
                output_format: outputFormat,
                vad_timeout_seconds: vadTimeout
            };

            askBtn.disabled = true;
            logToConsole(`Enviando /ask request: context_id=${contextId}, prompt="${ttsText}"`, 'info');

            try {
                const res = await fetch('/ask', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (res.status === 409) {
                    logToConsole("Error 409 Conflict: El motor está ocupado procesando otra solicitud.", "warning");
                    askBtn.disabled = false;
                    return;
                }

                if (!res.ok) {
                    const errorMsg = await res.text();
                    logToConsole(`Error del servidor (${res.status}): ${errorMsg}`, "error");
                    askBtn.disabled = false;
                    return;
                }

                const resp = await res.json();
                
                if (resp.status === 'success') {
                    let logMsg = `Solicitud completada con éxito.`;
                    if (resp.transcription) {
                        logMsg += `<br><b>Transcripción:</b> "${resp.transcription}"`;
                    }
                    if (resp.speaker) {
                        logMsg += `<br><b>Hablante verificado:</b> <span style="color: #34d399;">${resp.speaker}</span>`;
                    } else if (requireSpeakerId) {
                        logMsg += `<br><b>Hablante:</b> <span style="color: #f87171;">No verificado / Desconocido</span>`;
                    }
                    
                    logToConsole(logMsg, 'success');

                    if (resp.audio_wav_base64) {
                        const wavUrl = `data:audio/wav;base64,${resp.audio_wav_base64}`;
                        const audioContainer = document.createElement('div');
                        audioContainer.className = 'console-line success';
                        audioContainer.innerHTML = `<span class="console-line timestamp">[Audio Capturado]</span><br><audio class="audio-player" controls src="${wavUrl}"></audio>`;
                        consolePanel.appendChild(audioContainer);
                        consolePanel.scrollTop = consolePanel.scrollHeight;
                    }
                } else if (resp.status === 'silence_timeout') {
                    logToConsole("Error: Silencio detectado (Timeout VAD sin voz).", 'warning');
                } else if (resp.status === 'verification_failed') {
                    logToConsole("Error: Falló la verificación de identidad del hablante.", 'error');
                } else {
                    logToConsole(`Error del motor: ${resp.error_message || 'Desconocido'}`, 'error');
                }

            } catch (e) {
                logToConsole(`Error de conexión con el motor: ${e.message}`, 'error');
            } finally {
                askBtn.disabled = false;
            }
        }

        setInterval(pollStatus, 1000);
        pollStatus();
    </script>
</body>
</html>
"""

async def mqtt_loop(config: AppConfig, engine: AssistantEngine, state_manager: StateManager, source: AudioSource, sink: AudioSink):
    mqtt_cfg = config.interfaces.mqtt
    if not mqtt_cfg.enabled:
        logger.info("MQTT interface is disabled in configuration.")
        return

    broker = mqtt_cfg.broker
    port = mqtt_cfg.port
    prefix = mqtt_cfg.topic_prefix
    
    logger.info(f"Connecting to MQTT broker at {broker}:{port}...")
    
    def state_transition_hook(old_state, new_state):
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(mqtt_queue.put_nowait, (f"{prefix}/state", new_state))
        except RuntimeError:
            pass
        
    state_manager.set_hook(state_transition_hook)

    while True:
        try:
            async with MqttClient(broker, port) as client:
                logger.info("Connected to MQTT broker successfully.")
                await client.subscribe(f"{prefix}/ask/request")
                await client.subscribe(f"{prefix}/say/request")
                await client.publish(f"{prefix}/state", state_manager.current, qos=0)
                
                async def publish_worker():
                    try:
                        while True:
                            topic, payload = await mqtt_queue.get()
                            await client.publish(topic, payload, qos=0)
                            mqtt_queue.task_done()
                    except asyncio.CancelledError:
                        pass
                
                pub_task = asyncio.create_task(publish_worker())
                
                try:
                    async for message in client.messages:
                        if message.topic.matches(f"{prefix}/ask/request"):
                            try:
                                payload_str = message.payload.decode('utf-8')
                                data = json.loads(payload_str)
                                req = AskRequest.model_validate(data)
                                
                                logger.info(f"MQTT processing /ask request context_id={req.context_id}")
                                
                                async def run_and_publish(r=req):
                                    resp = await engine.ask(r, source, sink)
                                    resp_json = resp.model_dump_json()
                                    await client.publish(f"{prefix}/ask/result", resp_json, qos=0)
                                    
                                asyncio.create_task(run_and_publish())
                                
                            except Exception as ex:
                                logger.error(f"Error handling MQTT ask request: {ex}")
                        elif message.topic.matches(f"{prefix}/say/request"):
                            try:
                                payload_str = message.payload.decode('utf-8')
                                data = json.loads(payload_str)
                                req = SayRequest.model_validate(data)
                                
                                logger.info(f"MQTT processing /say request context_id={req.context_id}")
                                
                                async def run_and_publish_say(r=req):
                                    resp = await engine.say(r, sink)
                                    resp_json = resp.model_dump_json()
                                    await client.publish(f"{prefix}/say/result", resp_json, qos=0)
                                    
                                asyncio.create_task(run_and_publish_say())
                                
                            except Exception as ex:
                                logger.error(f"Error handling MQTT say request: {ex}")
                finally:
                    pub_task.cancel()
                    await pub_task
                    
        except asyncio.CancelledError:
            logger.info("MQTT loop cancelled.")
            break
        except Exception as e:
            logger.error(f"MQTT error: {e}. Retrying connection in 5 seconds...")
            await asyncio.sleep(5.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    mqtt_task = asyncio.create_task(mqtt_loop(
        app.state.config,
        app.state.engine,
        app.state.state_manager,
        app.state.source,
        app.state.sink
    ))
    yield
    mqtt_task.cancel()
    try:
        await mqtt_task
    except asyncio.CancelledError:
        pass
    app.state.ml_pool.close()

def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(
        title="Vocalis Voice Assistant I/O Engine",
        description="Async voice processing framework with HTTP and MQTT interfaces",
        version="1.1.0",
        lifespan=lifespan
    )
    
    app.state.config = config
    app.state.state_manager = StateManager()
    app.state.ml_pool = MLWorkerPool(config)
    app.state.engine = AssistantEngine(config, app.state.state_manager, app.state.ml_pool)
    
    app.state.source = SoundDeviceAudioSource(
        device_index=config.audio.input_device_index,
        sample_rate=config.audio.sample_rate,
        channels=config.audio.channels,
        chunk_size=config.audio.chunk_size,
        gain=config.audio.gain
    )
    app.state.sink = SoundDeviceAudioSink(
        device_index=config.audio.output_device_index,
        sample_rate=config.audio.sample_rate,
        channels=config.audio.channels
    )
    
    @app.post("/ask", response_model=AskResponse)
    async def ask(payload: AskRequest):
        resp = await app.state.engine.ask(payload, app.state.source, app.state.sink)
        if resp.status == "error" and "409 Conflict" in (resp.error_message or ""):
            raise HTTPException(status_code=409, detail=resp.error_message)
        return resp
        
    @app.post("/say", response_model=SayResponse)
    async def say(payload: SayRequest):
        resp = await app.state.engine.say(payload, app.state.sink)
        if resp.status == "error" and "409 Conflict" in (resp.error_message or ""):
            raise HTTPException(status_code=409, detail=resp.error_message)
        return resp
        
    @app.get("/status")
    async def status():
        return {"state": app.state.state_manager.current}

    if config.interfaces.http.enabled_ui:
        @app.get("/", response_class=HTMLResponse)
        async def read_root():
            return HTMLResponse(content=HTML_TEMPLATE, status_code=200)
        
    return app
