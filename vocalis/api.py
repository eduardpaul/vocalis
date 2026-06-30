import asyncio
import logging
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from fastapi.middleware.cors import CORSMiddleware
from aiomqtt import Client as MqttClient
from typing import AsyncGenerator, List, Set, Optional
import time
import random

api_key_query = APIKeyQuery(name="token", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(
    request: Request,
    api_key_q: Optional[str] = Depends(api_key_query),
    api_key_h: Optional[str] = Depends(api_key_header),
):
    expected_key = request.app.state.config.interfaces.http.api_key
    if not expected_key:
        return
    if api_key_q == expected_key or api_key_h == expected_key:
        return
    raise HTTPException(
        status_code=403, detail="Could not validate credentials"
    )

from vocalis.config import AppConfig
from vocalis.state import StateManager
from vocalis.audio import SoundDeviceAudioSource, SoundDeviceAudioSink, AudioSource, AudioSink
from vocalis.ml_workers import MLWorkerPool
from vocalis.orchestrator import AssistantEngine, AskRequest, AskResponse, SayRequest, SayResponse

logger = logging.getLogger("vocalis.api")

mqtt_queue = asyncio.Queue()


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("WebSocket client connected.")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info("WebSocket client disconnected.")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        payload_str = json.dumps(message)
        logger.debug(f"Broadcasting WebSocket message: {payload_str}")
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload_str)
            except Exception as e:
                logger.error(f"Error broadcasting to WebSocket connection: {e}")

ws_manager = ConnectionManager()

class MultiplexedAudioSource(AudioSource):
    def __init__(self, raw_source: AudioSource):
        self.raw_source = raw_source
        self.active_queue: Optional[asyncio.Queue] = None
        self._lock = asyncio.Lock()

    async def register_queue(self, queue: asyncio.Queue):
        async with self._lock:
            self.active_queue = queue

    async def unregister_queue(self):
        async with self._lock:
            self.active_queue = None

    async def push_chunk(self, chunk: bytes):
        async with self._lock:
            if self.active_queue is not None:
                self.active_queue.put_nowait(chunk)

    async def read_chunks(self) -> AsyncGenerator[bytes, None]:
        queue = asyncio.Queue()
        await self.register_queue(queue)
        try:
            while True:
                chunk = await queue.get()
                yield chunk
        finally:
            await self.unregister_queue()

async def background_audio_task(
    config: AppConfig,
    state_manager: StateManager,
    engine: AssistantEngine,
    raw_source: AudioSource,
    multiplexed_source: MultiplexedAudioSource,
    sink: AudioSink
):
    import numpy as np
    
    oww_model = None
    target_key = None
    
    if config.wakeword.enabled:
        logger.info("Initializing openWakeWord model inside background loop...")
        try:
            from openwakeword.model import Model as OWWModel
            oww_model = OWWModel(
                wakeword_models=[config.wakeword.model_path],
                inference_framework="onnx"
            )
            dummy_input = np.zeros(1280, dtype=np.int16)
            predictions = oww_model.predict(dummy_input)
            prediction_keys = list(predictions.keys())
            if prediction_keys:
                target_key = prediction_keys[0]
                logger.info(f"Loaded openWakeWord key: '{target_key}'")
            else:
                logger.error("No prediction keys loaded in openWakeWord model.")
        except Exception as e:
            logger.exception(f"Error initializing openWakeWord: {e}")
            logger.warning("Wakeword detection will be disabled.")
            oww_model = None

    samples_needed = 1280
    bytes_needed = samples_needed * 2
    audio_buffer = bytearray()

    logger.info("Background audio loop started reading chunks...")
    try:
        async for chunk in raw_source.read_chunks():
            if state_manager.current != "IDLE":
                await multiplexed_source.push_chunk(chunk)
            elif oww_model and target_key:
                audio_buffer.extend(chunk)
                while len(audio_buffer) >= bytes_needed:
                    chunk_bytes = audio_buffer[:bytes_needed]
                    del audio_buffer[:bytes_needed]
                    
                    pcm16 = np.frombuffer(chunk_bytes, dtype=np.int16)
                    predictions = oww_model.predict(pcm16)
                    score = predictions.get(target_key, 0.0)
                    
                    if score >= config.wakeword.threshold:
                        logger.info(f"WAKE DETECTED! (Score: {score:.3f})")
                        
                        await ws_manager.broadcast({
                            "event": "wake_detected",
                            "model": target_key,
                            "timestamp": time.time(),
                            "score": float(score)
                        })
                        
                        oww_model.reset()
                        audio_buffer.clear()
                        
                        if config.wakeword.auto_ask:
                            async def run_auto_ask():
                                prompt = random.choice(config.wakeword.wake_responses)
                                logger.info(f"Auto-ask wake prompt: '{prompt}'")
                                request = AskRequest(
                                    context_id=f"wake_{int(time.time())}",
                                    tts_text=prompt,
                                    require_speaker_id=False,
                                    output_format="both",
                                    barge_in=True,
                                    priority=config.wakeword.priority
                                )
                                try:
                                    result = await engine.ask(request, multiplexed_source, sink)
                                    logger.info(f"Auto-ask complete: status={result.status}, text='{result.transcription}'")
                                except Exception as err:
                                    logger.exception(f"Error in Auto-ask task: {err}")
                            
                            asyncio.create_task(run_auto_ask())
                        break
    except asyncio.CancelledError:
        logger.info("Background audio loop cancelled.")
    except Exception as e:
        logger.exception(f"Error in background audio loop: {e}")

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
    # Start engine queue worker
    app.state.engine.start(app.state.source, app.state.sink)

    # Start raw background audio task
    app.state.bg_audio_task = asyncio.create_task(background_audio_task(
        app.state.config,
        app.state.state_manager,
        app.state.engine,
        app.state.raw_source,
        app.state.source,
        app.state.sink
    ))

    # Set up WS broadcast state hook
    def ws_state_hook(old_state, new_state):
        asyncio.create_task(ws_manager.broadcast({
            "event": "state_change",
            "old_state": old_state,
            "new_state": new_state,
            "timestamp": time.time()
        }))
    app.state.state_manager.set_hook(ws_state_hook)

    # Set up completion hook to broadcast results to WebSockets
    def ws_completion_hook(result):
        if isinstance(result, AskResponse):
            payload = {
                "event": "ask_result",
                "status": result.status,
                "transcription": result.transcription,
                "speaker": result.speaker,
                "context_id": result.context_id,
                "audio_wav_base64": result.audio_wav_base64
            }
        else:
            payload = {
                "event": "say_result",
                "status": result.status,
                "context_id": result.context_id
            }
        asyncio.create_task(ws_manager.broadcast(payload))
    app.state.engine.set_completion_hook(ws_completion_hook)

    # Start MQTT task if enabled
    mqtt_task = None
    if app.state.config.interfaces.mqtt.enabled:
        mqtt_task = asyncio.create_task(mqtt_loop(
            app.state.config,
            app.state.engine,
            app.state.state_manager,
            app.state.source,
            app.state.sink
        ))

    yield

    # Clean up
    if mqtt_task:
        mqtt_task.cancel()
        try:
            await mqtt_task
        except asyncio.CancelledError:
            pass

    app.state.bg_audio_task.cancel()
    try:
        await app.state.bg_audio_task
    except asyncio.CancelledError:
        pass

    await app.state.engine.stop()
    app.state.ml_pool.close()


def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(
        title="Vocalis Voice Assistant I/O Engine",
        description="Async voice processing framework with HTTP and MQTT interfaces",
        version="1.1.0",
        lifespan=lifespan
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.state.config = config
    app.state.state_manager = StateManager()
    app.state.ml_pool = MLWorkerPool(config)
    app.state.engine = AssistantEngine(config, app.state.state_manager, app.state.ml_pool)
    
    app.state.raw_source = SoundDeviceAudioSource(
        device_index=config.audio.input_device_index,
        sample_rate=config.audio.sample_rate,
        channels=config.audio.channels,
        chunk_size=config.audio.chunk_size,
        gain=config.audio.gain
    )
    app.state.source = MultiplexedAudioSource(app.state.raw_source)
    app.state.sink = SoundDeviceAudioSink(
        device_index=config.audio.output_device_index,
        sample_rate=config.audio.sample_rate,
        channels=config.audio.channels
    )
    
    @app.post("/ask", response_model=AskResponse, dependencies=[Depends(verify_api_key)])
    async def ask(payload: AskRequest):
        resp = await app.state.engine.ask(payload, app.state.source, app.state.sink)
        if resp.status == "error" and "409 Conflict" in (resp.error_message or ""):
            raise HTTPException(status_code=409, detail=resp.error_message)
        return resp
        
    @app.post("/say", response_model=SayResponse, dependencies=[Depends(verify_api_key)])
    async def say(payload: SayRequest):
        resp = await app.state.engine.say(payload, app.state.sink)
        if resp.status == "error" and "409 Conflict" in (resp.error_message or ""):
            raise HTTPException(status_code=409, detail=resp.error_message)
        return resp
        
    @app.get("/status", dependencies=[Depends(verify_api_key)])
    async def status():
        return {"state": app.state.state_manager.current}

    @app.get("/queue", dependencies=[Depends(verify_api_key)])
    async def get_queue():
        q_list = []
        for q in app.state.engine.queue:
            q_list.append({
                "context_id": q.context_id,
                "type": q.type,
                "created_at": q.created_at
            })
        active = None
        if app.state.engine.current_active:
            active = {
                "context_id": app.state.engine.current_active.context_id,
                "type": app.state.engine.current_active.type,
                "created_at": app.state.engine.current_active.created_at
            }
        return {"active": active, "pending": q_list}

    @app.post("/queue/cancel/{context_id}", dependencies=[Depends(verify_api_key)])
    async def cancel_queue_item(context_id: str):
        success = await app.state.engine.cancel_request(context_id)
        return {"context_id": context_id, "success": success}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        expected_key = app.state.config.interfaces.http.api_key
        if expected_key:
            token = websocket.query_params.get("token")
            x_api_key = websocket.headers.get("x-api-key")
            if token != expected_key and x_api_key != expected_key:
                await websocket.accept()
                await websocket.send_json({
                    "event": "error",
                    "message": "Unauthorized: Invalid API Key"
                })
                await websocket.close(code=4003)
                return

        await ws_manager.connect(websocket)
        try:
            await websocket.send_json({
                "event": "handshake",
                "state": app.state.state_manager.current,
                "timestamp": time.time()
            })
            while True:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                    if payload.get("command") == "cancel":
                        ctx_id = payload.get("context_id")
                        if ctx_id:
                            success = await app.state.engine.cancel_request(ctx_id)
                            await websocket.send_json({
                                "event": "cancellation_result",
                                "context_id": ctx_id,
                                "success": success
                            })
                except Exception:
                    pass
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    @app.get("/")
    async def read_root():
        return {
            "status": "Vocalis Assistant Service is running",
            "version": "1.1.0",
            "system_name": config.system.name
        }
        
    return app
