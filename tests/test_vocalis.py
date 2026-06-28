import os
import asyncio
import logging
import pytest
import numpy as np
import soundfile as sf
from typing import AsyncGenerator

from vocalis.config import AppConfig
from vocalis.state import StateManager
from vocalis.audio import FileAudioSource, FileAudioSink, AudioSource
from vocalis.ml_workers import MLWorkerPool
from vocalis.orchestrator import AssistantEngine, AskRequest, AskResponse, SayRequest, SayResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vocalis.test")

def load_and_resample_wav(path: str, target_sr: int = 16000) -> bytes:
    data, sr = sf.read(path, dtype='float32')
    if data.ndim > 1:
        data = np.mean(data, axis=1)
    if sr != target_sr:
        num_samples = int(len(data) * target_sr / sr)
        data = np.interp(
            np.linspace(0, len(data), num_samples, endpoint=False),
            np.arange(len(data)),
            data
        ).astype(np.float32)
    # Convert to int16 PCM bytes
    samples_int16 = (data * 32767.0).astype(np.int16)
    return samples_int16.tobytes()

def register_test_speaker(config, ml_pool, name="verified_user"):
    demo_path = os.path.join(os.path.dirname(__file__), "data", "demo.wav")
    pcm_bytes = load_and_resample_wav(demo_path, target_sr=16000)
    stream = ml_pool.spk_extractor.create_stream()
    data = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    stream.accept_waveform(16000, data)
    stream.input_finished()
    embedding = ml_pool.spk_extractor.compute(stream)
    
    os.makedirs(config.models.speaker_id.embeddings_dir, exist_ok=True)
    speaker_file = os.path.join(config.models.speaker_id.embeddings_dir, f"{name}.npy")
    np.save(speaker_file, np.array(embedding, dtype=np.float32))
    ml_pool.load_known_speakers()

@pytest.fixture
def config(tmp_path):
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    cfg = AppConfig.load_yaml(config_path)
    cfg.resolve_paths(os.path.join(os.path.dirname(__file__), ".."))
    cfg.models.speaker_id.embeddings_dir = str(tmp_path / "known_speakers")
    os.makedirs(cfg.models.speaker_id.embeddings_dir, exist_ok=True)
    return cfg

@pytest.fixture
def ml_pool(config):
    pool = MLWorkerPool(config)
    yield pool
    pool.close()

def test_config(config):
    assert config.system.name == "living_room_node"
    assert config.audio.sample_rate == 16000
    assert config.models.vad.threshold == 0.5
    assert config.models.tts.engine == "supertonic"

@pytest.mark.asyncio
async def test_state_manager():
    sm = StateManager()
    assert sm.current == "IDLE"
    
    hook_called = []
    def hook(old, new):
        hook_called.append((old, new))
        
    sm.set_hook(hook)
    await sm.transition("SPEAKING")
    assert sm.current == "SPEAKING"
    assert hook_called == [("IDLE", "SPEAKING")]
    
    # Wait for idle timeout
    res = await sm.wait_for_idle(0.1)
    assert res is False
    
    await sm.transition("IDLE")
    res = await sm.wait_for_idle(0.1)
    assert res is True

class QueueAudioSource(AudioSource):
    def __init__(self):
        self.queue = asyncio.Queue()
        
    def push_file(self, path: str, chunk_size: int = 512):
        pcm_bytes = load_and_resample_wav(path, target_sr=16000)
        chunk_bytes_size = chunk_size * 2
        for i in range(0, len(pcm_bytes), chunk_bytes_size):
            chunk = pcm_bytes[i:i+chunk_bytes_size]
            if len(chunk) < chunk_bytes_size:
                chunk = chunk + b'\x00' * (chunk_bytes_size - len(chunk))
            self.queue.put_nowait(chunk)
        # Push sentinel
        self.queue.put_nowait(None)

    async def read_chunks(self) -> AsyncGenerator[bytes, None]:
        while True:
            chunk = await self.queue.get()
            if chunk is None:
                break
            yield chunk

@pytest.mark.asyncio
async def test_ml_asr(ml_pool):
    demo_path = os.path.join(os.path.dirname(__file__), "data", "demo.wav")
    assert os.path.exists(demo_path)
    
    pcm_bytes = load_and_resample_wav(demo_path, target_sr=16000)
    transcription = await ml_pool.run_asr(pcm_bytes)
    logger.info(f"Test ASR Moonshine text: '{transcription}'")
    assert len(transcription) > 0

@pytest.mark.asyncio
async def test_ml_tts(ml_pool):
    pcm = await ml_pool.run_tts("Hola, esta es una prueba de voz.")
    assert len(pcm) > 0
    assert len(pcm) % 2 == 0

@pytest.mark.asyncio
async def test_ml_speaker_verification(ml_pool, config):
    demo_path = os.path.join(os.path.dirname(__file__), "data", "demo.wav")
    pcm_bytes = load_and_resample_wav(demo_path, target_sr=16000)
    register_test_speaker(config, ml_pool, "verified_user")
    
    # Verify speaker search
    speaker, score = await ml_pool.run_speaker_verification(pcm_bytes)
    assert speaker == "verified_user"
    assert score >= config.models.speaker_id.confidence_threshold

@pytest.mark.asyncio
async def test_orchestrator_ask_success(config, ml_pool):
    sm = StateManager()
    engine = AssistantEngine(config, sm, ml_pool)
    
    source = QueueAudioSource()
    demo_path = os.path.join(os.path.dirname(__file__), "data", "demo.wav")
    source.push_file(demo_path)
    
    sink = FileAudioSink()
    
    req = AskRequest(
        context_id="test_ctx_1",
        tts_text="Hola",
        barge_in=False,
        require_speaker_id=False,
        output_format="text"
    )
    
    resp = await engine.ask(req, source, sink)
    assert resp.status == "success"
    assert resp.transcription is not None
    assert len(resp.transcription) > 0

@pytest.mark.asyncio
async def test_orchestrator_ask_with_speaker_id(config, ml_pool):
    config.models.speaker_id.confidence_threshold = 0.5
    register_test_speaker(config, ml_pool, "verified_user")
    sm = StateManager()
    engine = AssistantEngine(config, sm, ml_pool)
    
    source = QueueAudioSource()
    demo_path = os.path.join(os.path.dirname(__file__), "data", "demo.wav")
    source.push_file(demo_path)
    source.push_file(demo_path)
    
    sink = FileAudioSink()
    
    req = AskRequest(
        context_id="test_ctx_2",
        tts_text="Verificación de voz",
        barge_in=False,
        require_speaker_id=True,
        output_format="both"
    )
    
    resp = await engine.ask(req, source, sink)
    assert resp.status == "success"
    assert resp.speaker == "verified_user"
    assert resp.audio_wav_base64 is not None

@pytest.mark.asyncio
async def test_orchestrator_ask_with_speaker_id_failure(config, ml_pool):
    config.models.speaker_id.confidence_threshold = 0.99
    config.models.speaker_id.challenge_failed_prompt = "Fallo en el test"
    register_test_speaker(config, ml_pool, "verified_user")
    sm = StateManager()
    engine = AssistantEngine(config, sm, ml_pool)
    
    source = QueueAudioSource()
    demo_path = os.path.join(os.path.dirname(__file__), "data", "demo.wav")
    source.push_file(demo_path)
    source.push_file(demo_path)
    
    sink = FileAudioSink()
    
    req = AskRequest(
        context_id="test_ctx_3",
        tts_text="Verificación de voz",
        barge_in=False,
        require_speaker_id=True,
        output_format="both"
    )
    
    resp = await engine.ask(req, source, sink)
    assert resp.status == "verification_failed"
    assert len(sink.buffer) > 0

@pytest.mark.asyncio
async def test_orchestrator_say_success(config, ml_pool):
    sm = StateManager()
    engine = AssistantEngine(config, sm, ml_pool)
    
    sink = FileAudioSink()
    req = SayRequest(
        context_id="test_ctx_say",
        text="Hola, esto es una prueba de voz."
    )
    
    resp = await engine.say(req, sink)
    assert resp.status == "success"
    assert len(sink.buffer) > 0
