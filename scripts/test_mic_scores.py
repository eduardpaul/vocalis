#!/usr/bin/env python3
import os
import sys
import numpy as np
import sounddevice as sd
from openwakeword.model import Model as OWWModel

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from vocalis.config import AppConfig

def main():
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        print(f"Error: Config not found: {config_path}")
        sys.exit(1)

    config = AppConfig.load_yaml(config_path)
    config.resolve_paths(os.getcwd())

    project_root = os.path.dirname(script_dir)
    model_path = os.path.join(project_root, "models", "openwakeword_alfred.onnx")
    
    print(f"Loading model: {model_path}")
    oww_model = OWWModel(
        wakeword_models=[model_path],
        inference_framework="onnx"
    )
    
    target_key = list(oww_model.models.keys())[0]
    print(f"Model key: '{target_key}'")

    dev = config.audio.input_device_index
    if dev == "default":
        dev = None
    elif isinstance(dev, str) and dev.isdigit():
        dev = int(dev)

    print(f"\nRecording from device: {config.audio.input_device_index} (Gain: {config.audio.gain}x)")
    print("Speak the wake word ('Alfred' or 'Hey Alfred') repeatedly and watch the max score.")
    print("Press Ctrl+C to exit.\n")

    # Accumulator
    samples_per_read = 1280
    
    # We will track the highest score seen in the last 3 seconds
    max_score_recent = 0.0
    frames_since_reset = 0

    def callback(indata, frames, time_info, status):
        nonlocal max_score_recent, frames_since_reset
        if status:
            print(f"Status: {status}")
            
        samples = indata.flatten()
        if config.audio.gain != 1.0:
            samples = samples * config.audio.gain
            
        samples = np.clip(samples, -1.0, 1.0)
        pcm16 = (samples * 32767.0).astype(np.int16)
        
        predictions = oww_model.predict(pcm16)
        score = predictions.get(target_key, 0.0)
        
        if score > max_score_recent:
            max_score_recent = score
            
        frames_since_reset += 1
        if frames_since_reset >= 30: # ~2.4 seconds
            # Print recent peak
            print(f" -> Recent Peak Score: {max_score_recent:.4f}")
            max_score_recent = 0.0
            frames_since_reset = 0
            
        # Print instantaneous score
        rms = np.sqrt(np.mean(pcm16.astype(np.float32)**2)) if len(pcm16) > 0 else 0.0
        bar_len = int(rms / 100)
        bar = "=" * min(bar_len, 20)
        spaces = " " * (20 - len(bar))
        sys.stdout.write(f"\rVolume: [ {bar}{spaces} ] | Instant Score: {score:.4f}")
        sys.stdout.flush()

    try:
        stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            device=dev,
            callback=callback,
            blocksize=samples_per_read,
            dtype='float32'
        )
        with stream:
            while True:
                sd.sleep(100)
    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
