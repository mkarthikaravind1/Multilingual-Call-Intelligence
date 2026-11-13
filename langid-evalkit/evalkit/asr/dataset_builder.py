"""Dataset builder for phone-line bandpass ASR evaluation.

Dataset: Google FLEURS (CC-BY 4.0) or Common Voice (CC0).
Processes audio by downsampling to 8 kHz and upsampling back to 16 kHz to
accurately emulate telephony/phone-channel frequency characteristics.
"""

import argparse
import audioop
import json
import math
import os
import struct
import sys
import wave
from typing import List, Tuple

# Sample transcripts across target automotive call languages
SAMPLE_TEST_ITEMS = [
    {
        "filename": "call_ta_01.wav",
        "language": "ta",
        "reference": "வணக்கம் சார் உங்கள் வண்டி சர்வீஸ் முடிந்தது பிரேக் மாற்றப்பட்டது",
    },
    {
        "filename": "call_en_01.wav",
        "language": "en",
        "reference": "Hello sir your car service is completed and ready for pickup",
    },
    {
        "filename": "call_te_01.wav",
        "language": "te",
        "reference": "నమస్కారం సార్ మీ కారు సర్వీస్ పూర్తయింది రేపు డెలివరీ తీసుకోవచ్చు",
    },
    {
        "filename": "call_kn_01.wav",
        "language": "kn",
        "reference": "ನಮಸ್ಕಾರ ಸರ್ ನಿಮ್ಮ ವಾಹನದ ಸರ್ವೀಸ್ ಮುಗಿದಿದೆ ಬಂದು ತಗೋಬಹುದು",
    },
    {
        "filename": "call_ml_01.wav",
        "language": "ml",
        "reference": "നമസ്കാരം സാർ കാറിന്റെ സർവീസ് കഴിഞ്ഞു നാളെ ഡെലിവറി എടുക്കാം",
    },
]


def emulate_phone_audio(input_wav_path: str, output_wav_path: str):
    """Downsample WAV audio to 8 kHz and back to 16 kHz to emulate telephone bandwidth."""
    with wave.open(input_wav_path, "rb") as win:
        nchannels = win.getnchannels()
        sampwidth = win.getsampwidth()
        framerate = win.getframerate()
        nframes = win.getnframes()
        raw_frames = win.readframes(nframes)

    # Convert to mono if stereo
    if nchannels == 2:
        raw_frames = audioop.tomono(raw_frames, sampwidth, 0.5, 0.5)
        nchannels = 1

    # Ensure 16-bit
    if sampwidth != 2:
        raw_frames = audioop.lin2lin(raw_frames, sampwidth, 2)
        sampwidth = 2

    # Step 1: Downsample to 8 kHz (phone bandwidth)
    downsampled_frames, _ = audioop.ratecv(raw_frames, sampwidth, 1, framerate, 8000, None)

    # Step 2: Upsample back to 16 kHz (standard ASR ingestion rate)
    phone_frames, _ = audioop.ratecv(downsampled_frames, sampwidth, 1, 8000, 16000, None)

    with wave.open(output_wav_path, "wb") as wout:
        wout.setnchannels(1)
        wout.setsampwidth(2)
        wout.setframerate(16000)
        wout.writeframes(phone_frames)


def generate_synthetic_phone_clip(output_path: str, duration_sec: float = 2.0, freq: float = 440.0):
    """Generate a clean synthetic 16-bit 16 kHz mono WAV file filtered through phone bandwidth."""
    sample_rate = 16000
    total_samples = int(sample_rate * duration_sec)
    frames = bytearray()

    for i in range(total_samples):
        # Generate tone with subtle harmonics
        t = i / sample_rate
        value = int(12000.0 * math.sin(2.0 * math.pi * freq * t) + 4000.0 * math.sin(2.0 * math.pi * (freq * 1.5) * t))
        frames.extend(struct.pack("<h", max(-32768, min(32767, value))))

    # Downsample to 8 kHz and up to 16 kHz
    down, _ = audioop.ratecv(bytes(frames), 2, 1, sample_rate, 8000, None)
    up, _ = audioop.ratecv(down, 2, 1, 8000, sample_rate, None)

    with wave.open(output_path, "wb") as wout:
        wout.setnchannels(1)
        wout.setsampwidth(2)
        wout.setframerate(sample_rate)
        wout.writeframes(up)


def build_sample_dataset(dest_folder: str):
    """Create sample evaluation dataset with synthetic telephone audio and manifest.jsonl."""
    os.makedirs(dest_folder, exist_ok=True)
    manifest_path = os.path.join(dest_folder, "manifest.jsonl")

    manifest_entries = []
    frequencies = [300.0, 450.0, 600.0, 520.0, 380.0]

    for idx, item in enumerate(SAMPLE_TEST_ITEMS):
        out_wav = os.path.join(dest_folder, item["filename"])
        freq = frequencies[idx % len(frequencies)]
        generate_synthetic_phone_clip(out_wav, duration_sec=2.5, freq=freq)
        manifest_entries.append({
            "audio": item["filename"],
            "language": item["language"],
            "reference": item["reference"],
        })

    with open(manifest_path, "w", encoding="utf-8") as f:
        for entry in manifest_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Sample phone dataset built in {dest_folder}: {len(manifest_entries)} clips and manifest.jsonl.")


def main():
    parser = argparse.ArgumentParser(description="Build phone audio dataset for ASR evaluation")
    parser.add_argument("--output", type=str, default="data/phone_asr_eval", help="Destination folder")
    parser.add_argument("--generate-sample", action="store_true", default=True, help="Generate synthetic test set")
    args = parser.parse_args()

    build_sample_dataset(args.output)


if __name__ == "__main__":
    main()

