#!/usr/bin/env python3
import os
import sys
import argparse
import tempfile
import subprocess
import numpy as np
import soundfile as sf
import sherpa_onnx

from vocalis.config import AppConfig

def main():
    parser = argparse.ArgumentParser(description="Enroll a new speaker for Vocalis Speaker ID")
    parser.add_argument("--audio", nargs="+", help="Path to the speaker's enrollment audio file(s) (e.g. .wav, .m4a, .mp3)")
    parser.add_argument("--wav", nargs="+", help="Alias for --audio (for backward compatibility)")
    parser.add_argument("--name", required=True, help="Unique name/ID for the speaker (e.g. eduard)")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml (default: config.yaml)")
    args = parser.parse_args()

    audio_paths = args.audio or args.wav
    if not audio_paths:
        print("Error: Please specify the input audio file path(s) using --audio")
        sys.exit(1)

    for path in audio_paths:
        if not os.path.exists(path):
            print(f"Error: Input audio file not found: {path}")
            sys.exit(1)

    if not os.path.exists(args.config):
        print(f"Error: Configuration file not found: {args.config}")
        sys.exit(1)

    # 1. Load config
    config = AppConfig.load_yaml(args.config)
    config.resolve_paths(os.getcwd())

    # 2. Verify speaker ID model and VAD exist
    spk_model_path = config.models.speaker_id.model
    if not os.path.exists(spk_model_path):
        print(f"Error: Speaker identification model not found at {spk_model_path}")
        sys.exit(1)

    vad_model_path = config.models.vad.silero_onnx_path
    if not os.path.exists(vad_model_path):
        print(f"Error: VAD model not found at {vad_model_path}")
        sys.exit(1)

    # Initialize Extractor
    print(f"Loading CAM++ extractor...")
    spk_config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=spk_model_path,
        num_threads=1,
        provider="cpu"
    )
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(spk_config)

    # Setup VAD
    vad_config = sherpa_onnx.VadModelConfig()
    vad_config.silero_vad.model = vad_model_path
    vad_config.silero_vad.min_silence_duration = 0.5
    vad_config.silero_vad.min_speech_duration = 0.25
    vad_config.sample_rate = 16000

    embeddings = []

    # 3. Process and resample each audio file
    for audio_path in audio_paths:
        print(f"\nProcessing audio file: {audio_path}")
        
        temp_wav = None
        file_to_read = audio_path
        ext = os.path.splitext(audio_path)[1].lower()
        
        # If not a standard WAV file, use ffmpeg to decode it
        if ext != ".wav":
            temp_wav = os.path.join(tempfile.gettempdir(), f"vocalis_temp_enroll_{args.name}.wav")
            print(f"Decoding non-WAV format ({ext}) using ffmpeg to: {temp_wav}")
            
            cmd = [
                "ffmpeg", "-y", "-i", audio_path,
                "-ar", "16000", "-ac", "1",
                temp_wav
            ]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                file_to_read = temp_wav
            except Exception as e:
                print(f"Error: ffmpeg failed to decode the audio file: {e}")
                if os.path.exists(temp_wav):
                    os.remove(temp_wav)
                continue
                
        try:
            data, sr = sf.read(file_to_read, dtype='float32')
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            
            # Resample to 16000Hz if needed
            if sr != 16000:
                print(f"Resampling from {sr}Hz to 16000Hz...")
                num_samples = int(len(data) * 16000 / sr)
                data = np.interp(
                    np.linspace(0, len(data), num_samples, endpoint=False),
                    np.arange(len(data)),
                    data
                ).astype(np.float32)
        except Exception as e:
            print(f"Error reading audio file samples: {e}")
            continue
        finally:
            # Clean up temporary WAV file
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass

        # Apply VAD filter to extract speech segments
        print("Applying VAD filter to isolate active speech...")
        vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
        
        chunk_size = 512
        speech_segments = []
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i+chunk_size]
            if len(chunk) < chunk_size:
                chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
            vad.accept_waveform(chunk)
            
            while not vad.empty():
                speech_segments.append(np.array(vad.front.samples, dtype=np.float32))
                vad.pop()
                
        if speech_segments:
            speech_data = np.concatenate(speech_segments)
            speech_duration = len(speech_data) / 16000
            print(f"Isolated speech duration: {speech_duration:.2f} seconds")
        else:
            print("Warning: VAD did not detect any speech. Falling back to raw audio.")
            speech_data = data

        # Extract embedding
        stream = extractor.create_stream()
        stream.accept_waveform(16000, speech_data)
        stream.input_finished()
        
        if not extractor.is_ready(stream):
            print("Error: Audio sample too short. Skipping.")
            continue
            
        emb = np.array(extractor.compute(stream), dtype=np.float32)
        
        # Normalize vector
        emb_norm = emb / np.linalg.norm(emb)
        embeddings.append(emb_norm)

    if not embeddings:
        print("\nError: Could not extract any valid speaker embeddings from the input files.")
        sys.exit(1)

    # 4. Compute mean embedding and normalize it
    print(f"\nAveraging {len(embeddings)} normalized embeddings...")
    mean_embedding = np.mean(embeddings, axis=0)
    mean_embedding = mean_embedding / np.linalg.norm(mean_embedding)

    # 5. Save embedding
    embeddings_dir = config.models.speaker_id.embeddings_dir
    os.makedirs(embeddings_dir, exist_ok=True)
    target_path = os.path.join(embeddings_dir, f"{args.name.strip().lower()}.npy")
    
    np.save(target_path, mean_embedding)
    print(f"\nSuccess! Speaker '{args.name}' enrolled. Embedding saved to: {target_path}")

if __name__ == "__main__":
    main()
