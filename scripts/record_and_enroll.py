#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
import numpy as np
import sounddevice as sd
import soundfile as sf

from vocalis.config import AppConfig

def main():
    parser = argparse.ArgumentParser(description="Guided interactive speaker enrollment for Vocalis")
    parser.add_argument("--name", required=True, help="Unique name/ID for the speaker (e.g. eduard)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml (default: config.yaml)")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"Error: Configuration file not found: {args.config}")
        sys.exit(1)

    # 1. Load config to read prompts and audio settings
    config = AppConfig.load_yaml(args.config)
    config.resolve_paths(os.getcwd())

    init_prompt = config.models.speaker_id.challenge_init_prompt
    prompts = config.models.speaker_id.challenge_prompts

    if not prompts:
        print("Error: No challenge_prompts configured in config.yaml.")
        sys.exit(1)

    # Resolve device index
    dev = config.audio.input_device_index
    if dev == "default":
        dev = None
    elif isinstance(dev, str) and dev.isdigit():
        dev = int(dev)

    print("\n" + "="*50)
    print(" VOCALIS SPEAKER ID: INTERACTIVE ONBOARDING ")
    print("="*50)
    print(f"Speaker Identity     : {args.name}")
    print(f"Microphone Device    : {config.audio.input_device_index}")
    print(f"Gain Multiplier      : {config.audio.gain}x")
    print(f"Number of Phrases    : {len(prompts)}")
    print("-"*50)
    print("We will guide you through recording each challenge phrase to build a robust voiceprint.")
    print("Please stand at your typical distance from the microphone.")
    input("\nPress ENTER when you are ready to begin...")

    recorded_files = []
    temp_dir = "models/known_speakers/temp_enrollment"
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # 2. Interactive recording loop
        for idx, phrase in enumerate(prompts):
            print(f"\n--- Phrase [{idx+1}/{len(prompts)}] ---")
            print(f"👉 Say this: \033[1;35m\"{phrase}\"\033[0m")
            input("Press ENTER to start recording...")
            
            recording_data = []
            def callback(indata, frames, time, status):
                recording_data.append(indata.copy())
                
            try:
                stream = sd.InputStream(
                    samplerate=16000,
                    channels=1,
                    device=dev,
                    callback=callback,
                    dtype='float32'
                )
                with stream:
                    input("🔴 RECORDING... Press ENTER to stop.")
                print("🟢 Recording finished!")
            except Exception as e:
                print(f"\nError recording audio: {e}")
                sys.exit(1)

            if not recording_data:
                print("Error: Recording was too short. Skipping this phrase.")
                continue

            data = np.concatenate(recording_data, axis=0).flatten()
            
            # Apply digital gain if configured
            if config.audio.gain != 1.0:
                data = data * config.audio.gain
                data = np.clip(data, -1.0, 1.0)

            # Save temporary WAV file
            seg_file = f"{temp_dir}/{args.name}_phrase_{idx+1}.wav"
            sf.write(seg_file, data, 16000)
            recorded_files.append(seg_file)

        if not recorded_files:
            print("\nError: No phrases were successfully recorded.")
            sys.exit(1)

        # 3. Delegate ML extraction and registration to enroll_speaker.py
        print("\n" + "="*50)
        print(" PROCESSING RECORDINGS & REGISTERING PROFILE ")
        print("="*50)
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        enroll_path = os.path.join(script_dir, "enroll_speaker.py")
        
        cmd = [
            sys.executable, enroll_path,
            "--audio"
        ] + recorded_files + [
            "--name", args.name,
            "--config", args.config
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout)
        
        if result.returncode != 0:
            print("Error executing enrollment script:")
            print(result.stderr)
            sys.exit(1)

    finally:
        # 4. Clean up temporary audio files and folder
        for filepath in recorded_files:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
        if os.path.exists(temp_dir):
            try:
                os.rmdir(temp_dir)
            except OSError:
                pass

if __name__ == "__main__":
    main()
