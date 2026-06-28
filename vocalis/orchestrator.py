import logging
import asyncio
import random
import time
import base64
import io
import numpy as np
import soundfile as sf
from typing import Optional, Tuple, Dict, Any, Union, List
from pydantic import BaseModel, Field

from vocalis.config import AppConfig
from vocalis.state import StateManager
from vocalis.audio import AudioSource, AudioSink
from vocalis.ml_workers import MLWorkerPool

logger = logging.getLogger("vocalis.orchestrator")

# Data contracts matching System Design Specification
class AskRequest(BaseModel):
    context_id: str
    tts_text: str
    barge_in: bool = False
    require_speaker_id: bool = False
    output_format: str = "text"  # enum: ["text", "audio", "both"]
    vad_timeout_seconds: float = 10.0
    priority: int = 0  # higher values = higher priority

class AskResponse(BaseModel):
    context_id: str
    status: str  # success, silence_timeout, verification_failed, error
    transcription: Optional[str] = None
    speaker: Optional[str] = None
    audio_wav_base64: Optional[str] = None
    error_message: Optional[str] = None

class SayRequest(BaseModel):
    context_id: str
    text: str
    priority: int = 0  # higher values = higher priority

class SayResponse(BaseModel):
    context_id: str
    status: str  # success, error
    error_message: Optional[str] = None

def pcm_to_wav_base64(pcm_bytes: bytes, sample_rate: int = 16000) -> str:
    if not pcm_bytes:
        return ""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    wav_io = io.BytesIO()
    sf.write(wav_io, samples, sample_rate, format='WAV', subtype='PCM_16')
    return base64.b64encode(wav_io.getvalue()).decode('utf-8')

class QueuedRequest:
    def __init__(self, request: Union[AskRequest, SayRequest], future: asyncio.Future):
        self.request = request
        self.future = future
        self.context_id = request.context_id
        self.priority = getattr(request, "priority", 0)
        self.type = "ask" if isinstance(request, AskRequest) else "say"
        self.created_at = time.time()

class AssistantEngine:
    def __init__(self, config: AppConfig, state_manager: StateManager, ml_pool: MLWorkerPool):
        self.config = config
        self.state_manager = state_manager
        self.ml_pool = ml_pool
        self.queue: List[QueuedRequest] = []
        self.current_active: Optional[QueuedRequest] = None
        self._queue_lock = asyncio.Lock()
        self._worker_task: Optional[asyncio.Task] = None
        self._completion_hook = None

    def set_completion_hook(self, hook):
        self._completion_hook = hook

    def start(self, source: AudioSource, sink: AudioSink):
        self._worker_task = asyncio.create_task(self._queue_worker(source, sink))
        logger.info("AssistantEngine queue worker started.")

    async def stop(self):
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("AssistantEngine queue worker stopped.")

    async def _queue_worker(self, source: AudioSource, sink: AudioSink):
        while True:
            try:
                next_req = None
                async with self._queue_lock:
                    if self.queue:
                        next_req = self.queue.pop(0)
                        self.current_active = next_req

                if next_req is None:
                    await asyncio.sleep(0.05)
                    continue

                logger.info(f"Processing queued request: type={next_req.type}, context_id={next_req.context_id}")
                try:
                    if next_req.type == "ask":
                        res = await self._execute_ask_now(next_req.request, source, sink)
                        if not next_req.future.done():
                            next_req.future.set_result(res)
                        if self._completion_hook:
                            try:
                                self._completion_hook(res)
                            except Exception as ex:
                                logger.error(f"Error in completion hook: {ex}")
                    else:
                        res = await self._execute_say_now(next_req.request, sink)
                        if not next_req.future.done():
                            next_req.future.set_result(res)
                        if self._completion_hook:
                            try:
                                self._completion_hook(res)
                            except Exception as ex:
                                logger.error(f"Error in completion hook: {ex}")
                except Exception as e:
                    logger.exception(f"Error processing request {next_req.context_id}:")
                    if not next_req.future.done():
                        next_req.future.set_exception(e)
                finally:
                    self.current_active = None

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in AssistantEngine queue worker: {e}")
                await asyncio.sleep(1.0)

    async def _execute_ask_now(self, request: AskRequest, source: AudioSource, sink: AudioSink) -> AskResponse:
        logger.info(f"Received ask request with context_id: {request.context_id}")
        
        # Phase I: Gatecheck & Initialization
        max_wait = self.config.system.max_concurrency_wait
        is_idle = await self.state_manager.wait_for_idle(max_wait)
        if not is_idle:
            logger.warning("Concurrency conflict: System is busy.")
            return AskResponse(
                context_id=request.context_id,
                status="error",
                error_message="409 Conflict: Engine is not IDLE"
            )

        captured_audio = bytearray()
        
        try:
            # Phase II: Speech Synthesis & Output
            logger.info("Generating TTS prompt...")
            tts_pcm = await self.ml_pool.run_tts(request.tts_text)
            
            await self.state_manager.transition("SPEAKING")
            
            barge_in_triggered = False
            history_deque = None
            
            if not request.barge_in:
                # Block until playback finishes normally
                await sink.play(tts_pcm)
                # Introduce mandatory 150ms sleep to allow room acoustics/echoes to dissipate
                await asyncio.sleep(0.15)
            else:
                # Barge-in enabled: launch playback as task and monitor microphone stream
                logger.info("Barge-in enabled: starting background playback.")
                play_task = asyncio.create_task(sink.play(tts_pcm))
                barge_in_vad = self.ml_pool.create_vad()
                barge_in_triggered = False
                
                from collections import deque
                history_deque = deque(maxlen=50) # Approx 1.6 seconds of history at 32ms chunks
                
                barge_chunks_gen = source.read_chunks()
                try:
                    while not play_task.done():
                        # Read next chunk with timeout to prevent hanging on frozen streams
                        chunk = await asyncio.wait_for(barge_chunks_gen.__anext__(), timeout=1.0)
                        history_deque.append(chunk)
                        
                        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                        barge_in_vad.accept_waveform(samples)
                        
                        if barge_in_vad.is_speech_detected():
                            logger.info("Speech detected during playback: Triggering Barge-In!")
                            barge_in_triggered = True
                            await sink.abort()
                            play_task.cancel()
                            break
                except asyncio.TimeoutError:
                    logger.warning("Barge-in microphone stream timeout (no chunks received).")
                except StopAsyncIteration:
                    pass
                finally:
                    if not play_task.done():
                        play_task.cancel()
                        try:
                            await play_task
                        except asyncio.CancelledError:
                            pass
                
                if barge_in_triggered:
                    # Give room a short moment to clear after abrupt interruption
                    await asyncio.sleep(0.1)

            # Phase III: Primary Capture
            await self.state_manager.transition("LISTENING")
            vad = self.ml_pool.create_vad()
            start_time = asyncio.get_running_loop().time()
            speech_seen = False
            primary_chunks = []
            
            # Pre-populate with barge-in microphone history if barge-in occurred
            if barge_in_triggered and history_deque:
                logger.info(f"Pre-populating primary capture with {len(history_deque)} chunks from barge-in history.")
                for hist_chunk in history_deque:
                    primary_chunks.append(hist_chunk)
                    samples = np.frombuffer(hist_chunk, dtype=np.int16).astype(np.float32) / 32768.0
                    vad.accept_waveform(samples)
                    if vad.is_speech_detected():
                        speech_seen = True
                
                if not vad.empty():
                    seg = np.array(vad.front.samples, dtype=np.float32)
                    vad.pop()
                    captured_audio.extend((seg * 32767.0).astype(np.int16).tobytes())
                    logger.info("VAD segment retrieved from pre-populated barge-in history.")
            
            if not captured_audio:
                chunks_gen = source.read_chunks()
                try:
                    while True:
                        # Read next chunk with 2.0s timeout to prevent hanging on frozen streams
                        chunk = await asyncio.wait_for(chunks_gen.__anext__(), timeout=2.0)
                        
                        elapsed = asyncio.get_running_loop().time() - start_time
                        if elapsed >= request.vad_timeout_seconds:
                            logger.info("Primary capture VAD timeout reached.")
                            break
                            
                        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                        vad.accept_waveform(samples)
                        
                        if vad.is_speech_detected():
                            speech_seen = True
                            
                        if speech_seen:
                            primary_chunks.append(chunk)
                            
                        if not vad.empty():
                            seg = np.array(vad.front.samples, dtype=np.float32)
                            vad.pop()
                            captured_audio.extend((seg * 32767.0).astype(np.int16).tobytes())
                            logger.info("VAD segment retrieved successfully.")
                            break
                except asyncio.TimeoutError:
                    logger.warning("Microphone stream timeout (no chunks received for 2.0s). Ending capture.")
                except StopAsyncIteration:
                    pass
            
            # Fallback to whole captured buffer if segment was not cleanly completed
            if not captured_audio and speech_seen:
                captured_audio.extend(b"".join(primary_chunks))

            if not captured_audio:
                logger.info("No speech captured during listening window.")
                await self.state_manager.transition("IDLE")
                return AskResponse(
                    context_id=request.context_id,
                    status="silence_timeout"
                )

            # Phase IV: Inference & Challenge Loop
            await self.state_manager.transition("PROCESSING")
            transcription = await self.ml_pool.run_asr(bytes(captured_audio))
            logger.info(f"ASR Transcription: '{transcription}'")

            verified_speaker = None
            if request.require_speaker_id:
                audio_duration = len(captured_audio) / (2 * 16000)
                min_dur = self.config.models.speaker_id.min_audio_duration_seconds
                threshold = self.config.models.speaker_id.confidence_threshold
                
                score = 0.0
                matched_spk = None
                if audio_duration >= min_dur:
                    matched_spk, score = await self.ml_pool.run_speaker_verification(bytes(captured_audio))

                # Condition A: Audio too short OR similarity score < threshold
                if audio_duration < min_dur or matched_spk is None or score < threshold:
                    logger.info(f"Low confidence (score={score:.3f}, dur={audio_duration:.2f}s). Initiating challenge.")
                    
                    # Transition to CHALLENGING
                    await self.state_manager.transition("CHALLENGING")
                    challenge_prompt = random.choice(self.config.models.speaker_id.challenge_prompts)
                    challenge_text = f"{self.config.models.speaker_id.challenge_init_prompt}: {challenge_prompt}"
                    logger.info(f"Challenge prompt: '{challenge_text}'")
                    
                    challenge_tts_pcm = await self.ml_pool.run_tts(challenge_text)
                    await sink.play(challenge_tts_pcm)
                    await asyncio.sleep(0.15)
                    
                    # Capture secondary audio buffer
                    await self.state_manager.transition("LISTENING")
                    secondary_audio = bytearray()
                    secondary_vad = self.ml_pool.create_vad()
                    secondary_speech_seen = False
                    secondary_chunks = []
                    sec_start_time = asyncio.get_running_loop().time()
                    
                    sec_chunks_gen = source.read_chunks()
                    try:
                        while True:
                            # Read next chunk with 2.0s timeout to prevent hanging on frozen streams
                            chunk = await asyncio.wait_for(sec_chunks_gen.__anext__(), timeout=2.0)
                            
                            elapsed = asyncio.get_running_loop().time() - sec_start_time
                            if elapsed >= request.vad_timeout_seconds:
                                break
                            
                            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                            secondary_vad.accept_waveform(samples)
                            
                            if secondary_vad.is_speech_detected():
                                secondary_speech_seen = True
                                
                            if secondary_speech_seen:
                                secondary_chunks.append(chunk)
                                
                            if not secondary_vad.empty():
                                seg = np.array(secondary_vad.front.samples, dtype=np.float32)
                                secondary_vad.pop()
                                secondary_audio.extend((seg * 32767.0).astype(np.int16).tobytes())
                                break
                    except asyncio.TimeoutError:
                        logger.warning("Secondary microphone stream timeout (no chunks received for 2.0s). Ending capture.")
                    except StopAsyncIteration:
                        pass
                            
                    if not secondary_audio and secondary_speech_seen:
                        secondary_audio.extend(b"".join(secondary_chunks))
                        
                    if not secondary_audio:
                        logger.warning("No speech captured during challenge loop.")
                        fail_prompt = self.config.models.speaker_id.challenge_failed_prompt
                        await self.state_manager.transition("SPEAKING")
                        pcm_fail = await self.ml_pool.run_tts(fail_prompt)
                        await sink.play(pcm_fail)
                        
                        await self.state_manager.transition("IDLE")
                        return AskResponse(
                            context_id=request.context_id,
                            status="verification_failed"
                        )
                        
                    await self.state_manager.transition("PROCESSING")
                    matched_spk, score = await self.ml_pool.run_speaker_verification(bytes(secondary_audio))
                    
                    if matched_spk is not None and score >= threshold:
                        logger.info(f"Challenge verification successful: speaker={matched_spk}, score={score:.3f}")
                        verified_speaker = matched_spk
                    else:
                        logger.warning(f"Challenge verification failed: speaker={matched_spk}, score={score:.3f}")
                        fail_prompt = self.config.models.speaker_id.challenge_failed_prompt
                        await self.state_manager.transition("SPEAKING")
                        pcm_fail = await self.ml_pool.run_tts(fail_prompt)
                        await sink.play(pcm_fail)
                        
                        await self.state_manager.transition("IDLE")
                        return AskResponse(
                            context_id=request.context_id,
                            status="verification_failed"
                        )
                else:
                    logger.info(f"Speaker verification successful on primary audio: {matched_spk} (score={score:.3f})")
                    verified_speaker = matched_spk

            # Formulate response
            await self.state_manager.transition("IDLE")
            
            resp = AskResponse(
                context_id=request.context_id,
                status="success",
                transcription=transcription,
                speaker=verified_speaker
            )
            
            if request.output_format in ("audio", "both"):
                resp.audio_wav_base64 = pcm_to_wav_base64(bytes(captured_audio))
                
            if request.output_format == "audio":
                resp.transcription = None
                
            return resp

        except Exception as e:
            logger.exception("Error executing assistant ask engine:")
            await self.state_manager.transition("IDLE")
            return AskResponse(
                context_id=request.context_id,
                status="error",
                error_message=str(e)
            )

    async def _execute_say_now(self, request: SayRequest, sink: AudioSink) -> SayResponse:
        logger.info(f"Received say request with context_id: {request.context_id}")
        max_wait = self.config.system.max_concurrency_wait
        is_idle = await self.state_manager.wait_for_idle(max_wait)
        if not is_idle:
            logger.warning("Concurrency conflict: System is busy.")
            return SayResponse(
                context_id=request.context_id,
                status="error",
                error_message="409 Conflict: Engine is not IDLE"
            )

        try:
            logger.info("Generating TTS text...")
            tts_pcm = await self.ml_pool.run_tts(request.text)
            
            await self.state_manager.transition("SPEAKING")
            await sink.play(tts_pcm)
            await self.state_manager.transition("IDLE")
            
            return SayResponse(
                context_id=request.context_id,
                status="success"
            )
        except Exception as e:
            logger.exception("Error executing assistant say engine:")
            await self.state_manager.transition("IDLE")
            return SayResponse(
                context_id=request.context_id,
                status="error",
                error_message=str(e)
            )

    async def ask(self, request: AskRequest, source: AudioSource, sink: AudioSink) -> AskResponse:
        if self._worker_task is None or self._worker_task.done():
            logger.warning("Queue worker not running. Executing ask request directly.")
            res = await self._execute_ask_now(request, source, sink)
            if self._completion_hook:
                try:
                    self._completion_hook(res)
                except Exception as ex:
                    logger.error(f"Error in completion hook: {ex}")
            return res

        future = asyncio.get_running_loop().create_future()
        queued = QueuedRequest(request, future)

        async with self._queue_lock:
            for q in self.queue:
                if q.context_id == request.context_id:
                    return AskResponse(
                        context_id=request.context_id,
                        status="error",
                        error_message=f"Duplicate context_id in queue: {request.context_id}"
                    )
            if self.current_active and self.current_active.context_id == request.context_id:
                return AskResponse(
                    context_id=request.context_id,
                    status="error",
                    error_message=f"Duplicate context_id is currently active: {request.context_id}"
                )

            self.queue.append(queued)
            self.queue.sort(key=lambda x: (-x.priority, x.created_at))
            logger.info(f"Queued ask request context_id={request.context_id} (priority={request.priority}). Queue size: {len(self.queue)}")

        try:
            return await future
        except asyncio.CancelledError:
            return AskResponse(
                context_id=request.context_id,
                status="error",
                error_message="Request cancelled"
            )

    async def say(self, request: SayRequest, sink: AudioSink) -> SayResponse:
        if self._worker_task is None or self._worker_task.done():
            logger.warning("Queue worker not running. Executing say request directly.")
            res = await self._execute_say_now(request, sink)
            if self._completion_hook:
                try:
                    self._completion_hook(res)
                except Exception as ex:
                    logger.error(f"Error in completion hook: {ex}")
            return res

        future = asyncio.get_running_loop().create_future()
        queued = QueuedRequest(request, future)

        async with self._queue_lock:
            for q in self.queue:
                if q.context_id == request.context_id:
                    return SayResponse(
                        context_id=request.context_id,
                        status="error",
                        error_message=f"Duplicate context_id in queue: {request.context_id}"
                    )
            if self.current_active and self.current_active.context_id == request.context_id:
                return SayResponse(
                    context_id=request.context_id,
                    status="error",
                    error_message=f"Duplicate context_id is currently active: {request.context_id}"
                )

            self.queue.append(queued)
            self.queue.sort(key=lambda x: (-x.priority, x.created_at))
            logger.info(f"Queued say request context_id={request.context_id} (priority={request.priority}). Queue size: {len(self.queue)}")

        try:
            return await future
        except asyncio.CancelledError:
            return SayResponse(
                context_id=request.context_id,
                status="error",
                error_message="Request cancelled"
            )

    async def cancel_request(self, context_id: str) -> bool:
        async with self._queue_lock:
            for i, q in enumerate(self.queue):
                if q.context_id == context_id:
                    self.queue.pop(i)
                    q.future.cancel()
                    logger.info(f"Cancelled pending request context_id={context_id} in queue.")
                    return True

            if self.current_active and self.current_active.context_id == context_id:
                logger.info(f"Cancelling active request context_id={context_id}.")
                self.current_active.future.cancel()
                return True
        return False
