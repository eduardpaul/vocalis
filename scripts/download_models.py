#!/usr/bin/env python3
import os
import urllib.request
import sys
import tarfile

MODELS_INFO = {
    "wespeaker_en_voxceleb_CAM++.onnx": {
        "url": "https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main/wespeaker_en_voxceleb_CAM%2B%2B.onnx",
        "type": "file",
        "target": "wespeaker_en_voxceleb_CAM++.onnx"
    },
    "silero_vad.onnx": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
        "type": "file",
        "target": "silero_vad.onnx"
    },
    "sherpa-onnx-moonshine-base-es-quantized-2026-02-27": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-moonshine-base-es-quantized-2026-02-27.tar.bz2",
        "type": "directory",
        "target": "sherpa-onnx-moonshine-base-es-quantized-2026-02-27",
        "archive": "sherpa-onnx-moonshine-base-es-quantized-2026-02-27.tar.bz2"
    },
    "sherpa-onnx-supertonic-3-tts-int8-2026-05-11": {
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2",
        "type": "directory",
        "target": "sherpa-onnx-supertonic-3-tts-int8-2026-05-11",
        "archive": "sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2"
    }
}

TARGET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models"))

def create_report_progress(model_name):
    def report_progress(block_num, block_size, total_size):
        read_so_far = block_num * block_size
        if total_size > 0:
            percent = min(100, read_so_far * 100 / total_size)
            sys.stdout.write(f"\rDownloading {model_name}: {percent:.1f}% ({read_so_far / (1024*1024):.2f} MB / {total_size / (1024*1024):.2f} MB)")
        else:
            sys.stdout.write(f"\rDownloading {model_name}: {read_so_far / (1024*1024):.2f} MB")
        sys.stdout.flush()
    return report_progress

def main():
    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)
        print(f"Created directory: {TARGET_DIR}")

    print("="*60)
    print(" VOCALIS MODEL DOWNLOADER ")
    print("="*60)

    for name, info in MODELS_INFO.items():
        dest_path = os.path.join(TARGET_DIR, info["target"])
        
        # Check if already exists
        if os.path.exists(dest_path):
            print(f"[OK] Model already exists at: {dest_path}")
            continue

        print(f"\n[+] Preparing to download: {name}")
        
        if info["type"] == "file":
            print(f"    URL: {info['url']}")
            print(f"    Dest: {dest_path}")
            try:
                urllib.request.urlretrieve(info["url"], dest_path, create_report_progress(name))
                print(f"\n    [OK] Downloaded {name} successfully.")
            except Exception as e:
                print(f"\n    [ERROR] Failed to download {name}: {e}")
                sys.exit(1)
        elif info["type"] == "directory":
            archive_path = os.path.join(TARGET_DIR, info["archive"])
            print(f"    URL: {info['url']}")
            print(f"    Temp Archive: {archive_path}")
            
            # Download archive
            try:
                urllib.request.urlretrieve(info["url"], archive_path, create_report_progress(name))
                print(f"\n    [OK] Downloaded archive successfully.")
            except Exception as e:
                print(f"\n    [ERROR] Failed to download archive for {name}: {e}")
                if os.path.exists(archive_path):
                    os.remove(archive_path)
                sys.exit(1)
                
            # Extract archive
            try:
                print(f"    Extracting {info['archive']} into {TARGET_DIR}...")
                with tarfile.open(archive_path, "r:bz2") as tar:
                    tar.extractall(path=TARGET_DIR)
                print(f"    [OK] Extracted successfully.")
            except Exception as e:
                print(f"    [ERROR] Failed to extract {info['archive']}: {e}")
                sys.exit(1)
            finally:
                # Remove archive
                if os.path.exists(archive_path):
                    os.remove(archive_path)
                    print(f"    Cleaned up temp archive: {info['archive']}")
                    
    print("\n" + "="*60)
    print(" All models prepared and configured successfully! ")
    print("="*60)

if __name__ == "__main__":
    main()
