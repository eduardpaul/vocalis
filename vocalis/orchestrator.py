import logging
import asyncio
import random
import time
import base64
import io
import numpy as np
import soundfile as sf
from typing import Optional, Tuple, Dict, Any
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

class AssistantEngine:
    def __init__(self, config: AppConfig, state_manager: StateManager, ml_pool: MLWorkerPool):
        self.config = config
        self.state_manager = state_manager
        self.ml_pool = ml_pool

    async def ask(self, request: AskRequest, source: AudioSource, sink: AudioSink) -> AskResponse:
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
                
                try:
                    # Simultaneously read mic chunks for barge-in detection
                    async for chunk in source.read_chunks():
                        if play_task.done():
                            break
                        
                        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                        barge_in_vad.accept_waveform(samples)
                        
                        if barge_in_vad.is_speech_detected():
                            logger.info("Speech detected during playback: Triggering Barge-In!")
                            barge_in_triggered = True
                            await sink.abort()
                            play_task.cancel()
                            break
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
            
            async for chunk in source.read_chunks():
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
                    
                    async for chunk in source.read_chunks():
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

    async def say(self, request: SayRequest, sink: AudioSink) -> SayResponse:
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
