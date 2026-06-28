#!/usr/bin/env python3
import os
import sys
import asyncio
import numpy as np
import soundfile as sf

from vocalis.config import AppConfig
from vocalis.ml_workers import MLWorkerPool

async def main():
    print("=== Step 1: Loading Vocalis ML Models ===")
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        sys.exit(1)
        
    config = AppConfig.load_yaml(config_path)
    config.resolve_paths(os.getcwd())
    
    # Initialize ML pool
    ml_pool = MLWorkerPool(config)
    
    try:
        print("\n=== Step 2: Generating Synthetic Onboarding Voice for 'alfred' ===")
        prompts = config.models.speaker_id.challenge_prompts
        if not prompts:
            print("Error: No challenge_prompts found in config.yaml.")
            sys.exit(1)
            
        print(f"Synthesizing {len(prompts)} challenge prompts for enrollment...")
        all_pcm_bytes = bytearray()
        
        # 0.25 seconds of silence padding between phrases (8000 bytes)
        silence_padding = b'\x00' * int(16000 * 0.25 * 2)
        
        for idx, prompt in enumerate(prompts):
            print(f"[{idx+1}/{len(prompts)}] Synthesizing: '{prompt}'")
            pcm = await ml_pool.run_tts(prompt)
            if all_pcm_bytes:
                all_pcm_bytes.extend(silence_padding)
            all_pcm_bytes.extend(pcm)
            
        samples = np.frombuffer(bytes(all_pcm_bytes), dtype=np.int16).astype(np.float32) / 32767.0
        
        # Save to disk as alfred_user.wav
        enroll_wav = "alfred_user.wav"
        sf.write(enroll_wav, samples, 16000)
        print(f"Saved synthetic enrollment voice containing all phrases to: {enroll_wav}")
        
        print("\n=== Step 3: Enrolling Speaker 'alfred' ===")
        # Run enroll_speaker.py via subprocess to ensure standard onboarding execution
        import subprocess
        script_dir = os.path.dirname(os.path.abspath(__file__))
        enroll_path = os.path.join(script_dir, "enroll_speaker.py")
        cmd = [
            sys.executable, enroll_path,
            "--audio", enroll_wav,
            "--name", "alfred"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout)
        if result.returncode != 0:
            print("Error enrolling speaker 'alfred':", result.stderr)
            sys.exit(1)
            
        print("\n=== Step 4: Generating Separate Synthetic Verification Audio ===")
        # We generate a different phrase to verify generalization
        verification_text = "Por favor di mi voz es mi pasaporte."
        print(f"Synthesizing text: '{verification_text}'")
        
        pcm_verify_bytes = await ml_pool.run_tts(verification_text)
        verify_samples = np.frombuffer(pcm_verify_bytes, dtype=np.int16).astype(np.float32) / 32767.0
        
        verify_wav = "alfred_test.wav"
        sf.write(verify_wav, verify_samples, 16000)
        print(f"Saved synthetic verification voice to: {verify_wav}")
        
        print("\n=== Step 5: Reloading Speakers and Running Verification Test ===")
        # Reload ML pool known speakers to load 'alfred.npy'
        ml_pool.load_known_speakers()
        
        # Run verification on the test audio bytes
        speaker, score = await ml_pool.run_speaker_verification(pcm_verify_bytes)
        
        print("\n=== VERIFICATION RESULTS ===")
        print(f"Best Matched Speaker : {speaker}")
        print(f"Cosine Similarity Score: {score:.4f}")
        
        # Since both are synthetic voices from the same model, similarity should be very high
        if speaker == "alfred":
            print("SUCCESS: Voice verified successfully!")
        else:
            print("FAILURE: Voice verification matched the wrong speaker.")
            
    finally:
        ml_pool.close()

if __name__ == "__main__":
    asyncio.run(main())
