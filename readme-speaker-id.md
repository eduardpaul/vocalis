# Speaker Onboarding Guide: Vocalis Speaker ID

This document outlines the step-by-step process of onboarding, registering, and managing new speaker profiles in the *Vocalis* Voice Engine.

---

## How Speaker Identification Works in Vocalis

1. **CAM++ Embedding Extraction**: Vocalis uses the `wespeaker_en_voxceleb_CAM++.onnx` model to extract a 192-dimensional vector (embedding) that mathematically describes a speaker's unique vocal characteristics.
2. **Profile Storage**: Stored speaker profiles are saved as simple `.npy` (NumPy arrays) files inside the directory specified in `config.yaml` (`models/known_speakers/` by default). The filename (in lowercase, e.g., `edward.npy`) acts as the speaker's unique ID.
3. **Similarity Matching**: When a request sets `require_speaker_id: true`, Vocalis extracts the embedding of the captured speech, calculates the cosine similarity score against all stored speaker vectors, and assigns the speaker identity if the score is greater than or equal to `confidence_threshold`.

---

## Step-by-Step Onboarding Process

### Step 1: Guided Microphone Enrollment (Recommended)
To eliminate audio mismatch issues (e.g. volume or hardware frequency differences between devices), record your voiceprint directly using the configured hardware microphone by running:
```bash
python scripts/record_and_enroll.py --name maria
```
**Interactive Flow**:
1. The script loads the configured `challenge_prompts` from your `config.yaml`.
2. For each phrase, it prompts you: `👉 Say this: "<phrase>"`.
3. Press **ENTER** to start recording, speak the phrase, and then press **ENTER** again to stop recording.
4. After completing the recordings, the script filters each segment using VAD to isolate clean speech, extracts the normalized voice embeddings, computes their average (mean) vector, and registers the final profile:
   `models/known_speakers/maria.npy`

---

### Step 2: Alternative Onboarding (From Audio Files)
If you have pre-recorded audio files of a user speaking (or synthetic voices), you can enroll them using the CLI helper:
```bash
python scripts/enroll_speaker.py --audio maria_1.wav maria_2.m4a --name maria
```
This script decodes files using `ffmpeg`, applies VAD silence filtering, averages the embeddings, and saves `maria.npy`.

---

### Step 3: Verify the Registration
Check the `models/known_speakers/` directory. You should see the new profile file:
* `models/known_speakers/maria.npy`

---

## Active Challenge and Threshold Tuning

Vocalis leverages a confidence check when identifying speakers:
```yaml
models:
  speaker_id:
    confidence_threshold: 0.75
    min_audio_duration_seconds: 2.5
```

* **If the speaker matches with score $\ge$ 0.75**: The identification succeeds immediately.
* **If the audio is too short ($< 2.5$ seconds) OR the match score falls below 0.75**: Vocalis enters the **`CHALLENGING` state**. It plays a challenge prompt and asks the user to repeat it to capture a secondary segment for confirmation.

### Tuning the Threshold
* **0.70 to 0.80**: Recommended for high-security environments.
* **0.55 to 0.65**: Recommended for smart-home environments to decrease false challenges caused by variations in tone, distance from microphone, or short commands.
* **To adjust**: Edit the `confidence_threshold` key in `config.yaml` and restart the server.

---

## Managing Speaker Profiles
* **Rename Profile**: Simply rename the `.npy` file (e.g. rename `maria.npy` to `maria_admin.npy`). The filename is dynamically read on startup as the Speaker ID.
* **Delete Speaker**: Remove the corresponding `.npy` file from `models/known_speakers/`.
* **Note**: Any profile changes require restarting the Vocalis server or reloading the application context to take effect.
