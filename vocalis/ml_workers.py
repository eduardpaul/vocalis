import asyncio
import concurrent.futures
import numpy as np
import sherpa_onnx
import os
import glob
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger("vocalis.ml")

class MLWorkerPool:
    def __init__(self, config):
        self.config = config
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        
        # Load VAD
        vad_cfg = config.models.vad
        logger.info(f"Loading VAD model: {vad_cfg.silero_onnx_path}")
        self.vad_model_config = sherpa_onnx.VadModelConfig()
        self.vad_model_config.silero_vad.model = vad_cfg.silero_onnx_path
        self.vad_model_config.silero_vad.threshold = vad_cfg.threshold
        self.vad_model_config.silero_vad.min_silence_duration = vad_cfg.min_silence_duration_ms / 1000.0
        self.vad_model_config.silero_vad.min_speech_duration = 0.25
        self.vad_model_config.sample_rate = 16000
        self.vad_window_size = self.vad_model_config.silero_vad.window_size # 512
        
        # Load ASR (Moonshine Spanish offline)
        asr_cfg = config.models.asr
        logger.info(f"Loading Moonshine ASR model from: {asr_cfg.encoder}")
        self.asr = sherpa_onnx.OfflineRecognizer.from_moonshine_v2(
            encoder=asr_cfg.encoder,
            decoder=asr_cfg.decoder,
            tokens=asr_cfg.tokens,
            num_threads=2,
            provider="cpu"
        )
        
        # Load Speaker ID
        spk_cfg = config.models.speaker_id
        logger.info(f"Loading Speaker ID model: {spk_cfg.model}")
        spk_extractor_config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=spk_cfg.model,
            num_threads=1,
            provider="cpu"
        )
        self.spk_extractor = sherpa_onnx.SpeakerEmbeddingExtractor(spk_extractor_config)
        self.spk_manager = sherpa_onnx.SpeakerEmbeddingManager(self.spk_extractor.dim)
        
        # Load known speakers
        self.embeddings_dir = spk_cfg.embeddings_dir
        if not os.path.exists(self.embeddings_dir):
            os.makedirs(self.embeddings_dir)
        self.load_known_speakers()
        
        # Load TTS
        tts_cfg = config.models.tts
        logger.info(f"Loading Supertonic TTS model from: {tts_cfg.model_dir}")
        tts_config = sherpa_onnx.OfflineTtsConfig()
        tts_config.model.supertonic.duration_predictor = os.path.join(tts_cfg.model_dir, "duration_predictor.int8.onnx")
        tts_config.model.supertonic.text_encoder = os.path.join(tts_cfg.model_dir, "text_encoder.int8.onnx")
        tts_config.model.supertonic.vector_estimator = os.path.join(tts_cfg.model_dir, "vector_estimator.int8.onnx")
        tts_config.model.supertonic.vocoder = os.path.join(tts_cfg.model_dir, "vocoder.int8.onnx")
        tts_config.model.supertonic.tts_json = os.path.join(tts_cfg.model_dir, "tts.json")
        tts_config.model.supertonic.unicode_indexer = os.path.join(tts_cfg.model_dir, "unicode_indexer.bin")
        tts_config.model.supertonic.voice_style = os.path.join(tts_cfg.model_dir, "voice.bin")
        tts_config.model.num_threads = 2
        tts_config.model.provider = "cpu"
        self.tts = sherpa_onnx.OfflineTts(tts_config)

    def load_known_speakers(self):
        pattern = os.path.join(self.embeddings_dir, "*.npy")
        for filepath in glob.glob(pattern):
            name = os.path.splitext(os.path.basename(filepath))[0]
            try:
                emb = np.load(filepath)
                if len(emb) == self.spk_extractor.dim:
                    self.spk_manager.add(name, list(emb))
                    logger.info(f"Loaded speaker profile: {name} ({filepath})")
                else:
                    logger.error(f"Speaker profile {name} dim mismatch: got {len(emb)}, expected {self.spk_extractor.dim}")
            except Exception as e:
                logger.error(f"Error loading speaker profile {name}: {e}")

    def create_vad(self) -> sherpa_onnx.VoiceActivityDetector:
        return sherpa_onnx.VoiceActivityDetector(self.vad_model_config, buffer_size_in_seconds=30)

    async def run_asr(self, pcm_bytes: bytes) -> str:
        """Decodes the given PCM bytes using Moonshine ASR in a thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self._run_asr_sync, pcm_bytes)

    def _run_asr_sync(self, pcm_bytes: bytes) -> str:
        if not pcm_bytes:
            return ""
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Pad with 0.35 seconds of silence at start/end to stabilize Moonshine
        pad_samples = int(0.35 * 16000)
        silence = np.zeros(pad_samples, dtype=np.float32)
        waveform = np.concatenate([silence, samples, silence])
        
        stream = self.asr.create_stream()
        stream.accept_waveform(16000, waveform)
        self.asr.decode_stream(stream)
        result = stream.result
        if hasattr(result, "text"):
            return result.text.strip()
        return str(result).strip()

    async def run_speaker_verification(self, pcm_bytes: bytes) -> Tuple[Optional[str], float]:
        """Runs CAM++ speaker verification in a thread pool. Returns (matched_speaker, score)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self._run_speaker_verification_sync, pcm_bytes)

    def _run_speaker_verification_sync(self, pcm_bytes: bytes) -> Tuple[Optional[str], float]:
        if not pcm_bytes:
            return None, 0.0
            
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        stream = self.spk_extractor.create_stream()
        stream.accept_waveform(16000, samples)
        stream.input_finished()
        
        if not self.spk_extractor.is_ready(stream):
            logger.warning("Audio duration too short for speaker embedding extraction.")
            return None, 0.0
            
        embedding = self.spk_extractor.compute(stream)
        
        best_speaker = None
        best_score = -1.0
        for speaker in self.spk_manager.all_speakers:
            score = self.spk_manager.score(speaker, embedding)
            if score > best_score:
                best_score = score
                best_speaker = speaker
                
        logger.info(f"Speaker verification score: best={best_speaker}, score={best_score:.3f}")
        return best_speaker, best_score

    async def run_tts(self, text: str) -> bytes:
        """Synthesizes the text using Supertonic TTS in a thread pool and returns PCM bytes."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self._run_tts_sync, text)

    def _run_tts_sync(self, text: str) -> bytes:
        gen_config = sherpa_onnx.GenerationConfig()
        gen_config.sid = 9
        gen_config.num_steps = 8
        gen_config.speed = 1.0
        gen_config.extra = {"lang": "es"}
        
        audio = self.tts.generate(text, gen_config)
        samples = np.array(audio.samples, dtype=np.float32)
        if audio.sample_rate != 16000:
            num_samples = int(len(samples) * 16000 / audio.sample_rate)
            samples = np.interp(
                np.linspace(0, len(samples), num_samples, endpoint=False),
                np.arange(len(samples)),
                samples
            ).astype(np.float32)
        samples_int16 = (samples * 32767.0).astype(np.int16)
        return samples_int16.tobytes()

    def close(self):
        self.executor.shutdown(wait=True)
