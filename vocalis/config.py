import os
import yaml
from typing import List, Optional, Union
from pydantic import BaseModel, Field, model_validator

class SystemConfig(BaseModel):
    name: str = "living_room_node"
    log_level: str = "INFO"
    max_concurrency_wait: float = 5.0

class HttpInterfaceConfig(BaseModel):
    enabled: bool = True
    enabled_ui: bool = True
    host: str = "0.0.0.0"
    port: int = 8080

class MqttInterfaceConfig(BaseModel):
    enabled: bool = True
    broker: str = "localhost"
    port: int = 1883
    topic_prefix: str = "home/assistant/node1"

class InterfacesConfig(BaseModel):
    http: HttpInterfaceConfig = Field(default_factory=HttpInterfaceConfig)
    mqtt: MqttInterfaceConfig = Field(default_factory=MqttInterfaceConfig)

class AudioConfig(BaseModel):
    input_device_index: Union[int, str] = "default"
    output_device_index: Union[int, str] = "default"
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 512
    gain: float = 1.0

class VadConfig(BaseModel):
    silero_onnx_path: str = "./models/silero_vad.onnx"
    threshold: float = 0.5
    min_silence_duration_ms: int = 700

class AsrConfig(BaseModel):
    encoder: str = ""
    decoder: str = ""
    tokens: str = ""

class SpeakerIdConfig(BaseModel):
    model: str = ""
    embeddings_dir: str = ""
    min_audio_duration_seconds: float = 2.5
    confidence_threshold: float = 0.75
    challenge_failed_prompt: str = "Acceso denegado. Verificación de voz fallida."
    challenge_init_prompt: str = "Por favor, repita"
    challenge_prompts: List[str] = Field(default_factory=list)

    @model_validator(mode='before')
    @classmethod
    def handle_init_promt(cls, values):
        if isinstance(values, dict):
            if 'challenge_init_promt' in values and 'challenge_init_prompt' not in values:
                values['challenge_init_prompt'] = values['challenge_init_promt']
        return values

class TtsConfig(BaseModel):
    engine: str = "supertonic"
    model_dir: str = ""

class ModelsConfig(BaseModel):
    vad: VadConfig = Field(default_factory=VadConfig)
    asr: AsrConfig = Field(default_factory=AsrConfig)
    speaker_id: SpeakerIdConfig = Field(default_factory=SpeakerIdConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)

class AppConfig(BaseModel):
    system: SystemConfig = Field(default_factory=SystemConfig)
    interfaces: InterfacesConfig = Field(default_factory=InterfacesConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)

    @classmethod
    def load_yaml(cls, path: str) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def resolve_paths(self, base_dir: str):
        def resolve(p: str) -> str:
            if not p:
                return p
            if os.path.isabs(p):
                return p
            return os.path.abspath(os.path.join(base_dir, p))

        self.models.vad.silero_onnx_path = resolve(self.models.vad.silero_onnx_path)
        self.models.asr.encoder = resolve(self.models.asr.encoder)
        self.models.asr.decoder = resolve(self.models.asr.decoder)
        self.models.asr.tokens = resolve(self.models.asr.tokens)
        self.models.speaker_id.model = resolve(self.models.speaker_id.model)
        self.models.speaker_id.embeddings_dir = resolve(self.models.speaker_id.embeddings_dir)
        self.models.tts.model_dir = resolve(self.models.tts.model_dir)
