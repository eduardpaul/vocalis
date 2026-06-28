import os
import sys
import uvicorn
import logging
import asyncio
from vocalis.config import AppConfig
from vocalis.api import create_app, mqtt_loop
from vocalis.state import StateManager
from vocalis.ml_workers import MLWorkerPool
from vocalis.orchestrator import AssistantEngine
from vocalis.audio import SoundDeviceAudioSource, SoundDeviceAudioSink

def main():
    # Find and load configuration
    config_path = os.path.join(os.getcwd(), "config.yaml")
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        sys.exit(1)
        
    config = AppConfig.load_yaml(config_path)
    config.resolve_paths(os.getcwd())

    # Configure logging
    log_level = getattr(logging, config.system.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout
    )
    
    logger = logging.getLogger("vocalis.main")
    logger.info(f"Starting Vocalis Assistant: '{config.system.name}'")
    
    if config.interfaces.http.enabled:
        logger.info("HTTP interface is enabled. Starting FastAPI server...")
        app = create_app(config)
        host = config.interfaces.http.host
        port = config.interfaces.http.port
        uvicorn.run(app, host=host, port=port)
    else:
        logger.info("HTTP interface is disabled. Running in standalone MQTT daemon mode.")
        if not config.interfaces.mqtt.enabled:
            logger.error("Error: Both HTTP and MQTT interfaces are disabled. Nothing to run!")
            sys.exit(1)
            
        async def run_standalone_mqtt():
            state_manager = StateManager()
            ml_pool = MLWorkerPool(config)
            engine = AssistantEngine(config, state_manager, ml_pool)
            
            source = SoundDeviceAudioSource(
                device_index=config.audio.input_device_index,
                sample_rate=config.audio.sample_rate,
                channels=config.audio.channels,
                chunk_size=config.audio.chunk_size,
                gain=config.audio.gain
            )
            sink = SoundDeviceAudioSink(
                device_index=config.audio.output_device_index,
                sample_rate=config.audio.sample_rate,
                channels=config.audio.channels
            )
            
            try:
                await mqtt_loop(config, engine, state_manager, source, sink)
            finally:
                ml_pool.close()

        try:
            asyncio.run(run_standalone_mqtt())
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt detected. Shutting down Standalone MQTT mode...")

if __name__ == "__main__":
    main()
