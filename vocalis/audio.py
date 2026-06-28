import asyncio
import numpy as np
import sounddevice as sd
import soundfile as sf
import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger("vocalis.audio")

class AudioSource:
    async def read_chunks(self) -> AsyncGenerator[bytes, None]:
        """Asynchronously yield chunks of raw mono 16-bit PCM bytes at 16kHz."""
        raise NotImplementedError
        yield b""

class SoundDeviceAudioSource(AudioSource):
    def __init__(self, device_index: int | str, sample_rate: int = 16000, channels: int = 1, chunk_size: int = 512, gain: float = 1.0):
        self.device = device_index if device_index != "default" else None
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.gain = gain
        self.queue = asyncio.Queue()
        self.stream = None
        self.loop = None

    def _callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"Audio input status: {status}")
        # Convert float32 [-1, 1] samples to signed 16-bit PCM bytes
        samples = indata
        if self.gain != 1.0:
            samples = samples * self.gain
        samples = np.clip(samples, -1.0, 1.0)
        samples_int16 = (samples * 32767.0).astype(np.int16)
        data_bytes = samples_int16.tobytes()
        if self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(self.queue.put_nowait, data_bytes)
            except RuntimeError:
                pass

    async def open(self):
        self.loop = asyncio.get_running_loop()
        dev = self.device
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)
        
        self.stream = sd.InputStream(
            device=dev,
            samplerate=self.sample_rate,
            channels=self.channels,
            callback=self._callback,
            blocksize=self.chunk_size,
            dtype='float32'
        )
        self.stream.start()
        logger.info(f"SoundDeviceAudioSource started on device {dev or 'default'}")

    async def close(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            logger.info("SoundDeviceAudioSource stopped")

    async def read_chunks(self) -> AsyncGenerator[bytes, None]:
        try:
            await self.open()
            while True:
                chunk = await self.queue.get()
                yield chunk
        finally:
            await self.close()

class FileAudioSource(AudioSource):
    def __init__(self, file_path: str, chunk_size: int = 512, sample_rate: int = 16000):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.sample_rate = sample_rate

    async def read_chunks(self) -> AsyncGenerator[bytes, None]:
        logger.info(f"FileAudioSource reading from: {self.file_path}")
        # Read file
        data, sr = sf.read(self.file_path, dtype='float32')
        if sr != self.sample_rate:
            # Resample to sample_rate using numpy.interp
            num_samples = int(len(data) * self.sample_rate / sr)
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            data = np.interp(
                np.linspace(0, len(data), num_samples, endpoint=False),
                np.arange(len(data)),
                data
            ).astype(np.float32)
        else:
            if data.ndim > 1:
                data = np.mean(data, axis=1)

        # Convert to 16-bit signed PCM
        samples = (data * 32767.0).astype(np.int16)
        data_bytes = samples.tobytes()

        chunk_bytes_size = self.chunk_size * 2  # 2 bytes per sample (16-bit Mono)
        sleep_duration = self.chunk_size / self.sample_rate

        for i in range(0, len(data_bytes), chunk_bytes_size):
            chunk = data_bytes[i:i + chunk_bytes_size]
            if len(chunk) < chunk_bytes_size:
                chunk = chunk + b'\x00' * (chunk_bytes_size - len(chunk))
            yield chunk
            await asyncio.sleep(sleep_duration)

class AudioSink:
    async def play(self, pcm_bytes: bytes) -> None:
        """Asynchronously play 16-bit PCM bytes."""
        raise NotImplementedError

    async def abort(self) -> None:
        """Instantly stop any active hardware output buffers."""
        raise NotImplementedError

class SoundDeviceAudioSink(AudioSink):
    def __init__(self, device_index: int | str, sample_rate: int = 16000, channels: int = 1):
        self.device = device_index if device_index != "default" else None
        self.sample_rate = sample_rate
        self.channels = channels
        self._playback_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def _play_task_fn(self, samples, dev):
        try:
            sd.play(samples, samplerate=self.sample_rate, device=dev)
            duration = len(samples) / self.sample_rate
            await asyncio.sleep(duration)
        finally:
            sd.stop()

    async def play(self, pcm_bytes: bytes) -> None:
        async with self._lock:
            await self._abort_under_lock()

            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            dev = self.device
            if isinstance(dev, str) and dev.isdigit():
                dev = int(dev)

            self._playback_task = asyncio.create_task(self._play_task_fn(samples, dev))
            logger.info("SoundDeviceAudioSink starting playback...")
            task = self._playback_task

        # Await the task outside the lock to avoid deadlock when calling abort()
        try:
            await task
            logger.info("SoundDeviceAudioSink playback completed normally")
        except asyncio.CancelledError:
            logger.info("SoundDeviceAudioSink playback aborted via cancellation")
        finally:
            async with self._lock:
                if self._playback_task == task:
                    self._playback_task = None

    async def _abort_under_lock(self) -> None:
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
            self._playback_task = None

    async def abort(self) -> None:
        async with self._lock:
            await self._abort_under_lock()

class FileAudioSink(AudioSink):
    def __init__(self, output_path: Optional[str] = None):
        self.output_path = output_path
        self.buffer = bytearray()
        self._playback_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def play(self, pcm_bytes: bytes) -> None:
        async with self._lock:
            if self._playback_task and not self._playback_task.done():
                self._playback_task.cancel()
                try:
                    await self._playback_task
                except asyncio.CancelledError:
                    pass
                self._playback_task = None

            self.buffer.extend(pcm_bytes)
            
            if self.output_path:
                samples = np.frombuffer(self.buffer, dtype=np.int16).astype(np.float32) / 32768.0
                sf.write(self.output_path, samples, 16000)

            # Simulate hardware play duration in asyncio
            duration = (len(pcm_bytes) / 2) / 16000
            self._playback_task = asyncio.create_task(asyncio.sleep(duration))
            task = self._playback_task

        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            async with self._lock:
                if self._playback_task == task:
                    self._playback_task = None

    async def abort(self) -> None:
        async with self._lock:
            if self._playback_task and not self._playback_task.done():
                self._playback_task.cancel()
                self._playback_task = None
