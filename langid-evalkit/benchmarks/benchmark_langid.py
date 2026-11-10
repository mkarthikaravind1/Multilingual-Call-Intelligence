"""Benchmark script for langid accuracy and CPU latency."""

import time
from typing import Dict, List, Tuple
from langid import identify

TEST_CORPUS: List[Tuple[str, List[str], str]] = [
    # (Text, expected_languages, description)
    # Native Tamil
    ("வணக்கம் சார் உங்கள் வண்டி சர்வீஸ் முடிந்தது பிரேக் மாற்றப்பட்டது", ["ta"], "Native Tamil"),
    ("என் காரில் ஏசி வேலை செய்யவில்லை பில் அதிகம்", ["ta"], "Native Tamil"),
    # Native Telugu
    ("నమస్కారం సార్ మీ కారు సర్వీస్ పూర్తయింది రేపు డెలివరీ తీసుకోవచ్చు", ["te"], "Native Telugu"),
    ("ఇంజిన్ ఆయిల్ మార్చారా లేదా సార్", ["te"], "Native Telugu"),
    # Native Kannada
    ("ನಮಸ್ಕಾರ ಸರ್ ನಿಮ್ಮ ವಾಹನದ ಸರ್ವೀಸ್ ಮುಗಿದಿದೆ ಬಂದು ತಗೋಬಹುದು", ["kn"], "Native Kannada"),
    ("ಬ್ರೇಕ್ ಸರಿ ಇಲ್ಲ ಸರ್ ಬಹಳ ಶಬ್ದ ಬರುತ್ತಿದೆ", ["kn"], "Native Kannada"),
    # Native Malayalam
    ("നമസ്കാരം സാർ കാറിന്റെ സർവീസ് കഴിഞ്ഞു നാളെ ഡെലിവറി എടുക്കാം", ["ml"], "Native Malayalam"),
    ("വണ്ടിക്ക് എയർ കണ്ടീഷൻ തണുപ്പില്ല", ["ml"], "Native Malayalam"),
    # Pure English
    ("Good morning sir your vehicle brake pads have been replaced today", ["en"], "Pure English"),
    ("The delivery turnaround time was delayed by three hours", ["en"], "Pure English"),
    ("Customer service advisor was extremely rude and unhelpful", ["en"], "Pure English"),
    # Romanised Tamil (Tanglish) code-mixed
    ("enna problem sir, brake sariya work aagala", ["ta", "en"], "Tanglish Code-mixed"),
    ("vanakkam sir bill romba costly a irukku enna aachu", ["ta", "en"], "Tanglish Code-mixed"),
    ("vandi romba dirty a irukku clean panna maari theriyala", ["ta", "en"], "Tanglish Code-mixed"),
    # Romanised Telugu (Tenglish) code-mixed
    ("enti problem babu engine lo sound vastundi cheppandi", ["te", "en"], "Tenglish Code-mixed"),
    ("namaskaram andi car delivery eppudu ivvandi", ["te", "en"], "Tenglish Code-mixed"),
    # Romanised Kannada (Kanglish) code-mixed
    ("enu problem agide sir service thumba delay agilla", ["kn", "en"], "Kanglish Code-mixed"),
    ("namaskara sir battery change madabeku nodona", ["kn", "en"], "Kanglish Code-mixed"),
    # Romanised Malayalam (Manglish) code-mixed
    ("entha problem aanu sir brake work aavunnilla", ["ml", "en"], "Manglish Code-mixed"),
    ("namaskaram sir car wash nannayi cheyyanam", ["ml", "en"], "Manglish Code-mixed"),
    # Edge cases
    ("", [], "Empty text"),
    ("   ", [], "Whitespace text"),
    ("1234567890", [], "Digits only"),
    ("!@#$%^&*()_+", [], "Symbols only"),
]


def run_benchmark():
    correct = 0
    total = len(TEST_CORPUS)

    print("=" * 70)
    print(" LANGID ACCURACY BENCHMARK")
    print("=" * 70)

    for text, expected_langs, desc in TEST_CORPUS:
        results = identify(text)
        detected_langs = [r["language"] for r in results]

        # Check match
        if expected_langs == []:
            match = (results == [])
        else:
            # All expected languages must be present
            match = set(expected_langs).issubset(set(detected_langs))

        if match:
            correct += 1
            status = "PASS"
        else:
            status = "FAIL"

        print(f"[{status}] {desc:<22} | Expected: {str(expected_langs):<12} | Got: {str(detected_langs):<12} | '{text[:30]}...'")

    accuracy = (correct / total) * 100.0
    print("-" * 70)
    print(f"Total Test Cases : {total}")
    print(f"Correct Matches  : {correct}")
    print(f"Accuracy         : {accuracy:.2f}%")
    print("=" * 70)

    # Speed Benchmark
    sample_text = "enna problem sir, brake sariya work aagala"
    iterations = 10000
    # Warmup
    for _ in range(500):
        identify(sample_text)

    t0 = time.perf_counter()
    for _ in range(iterations):
        identify(sample_text)
    total_time = time.perf_counter() - t0
    avg_latency_us = (total_time / iterations) * 1_000_000.0
    avg_latency_ms = avg_latency_us / 1000.0

    print("\n" + "=" * 70)
    print(" LANGID SPEED & LATENCY BENCHMARK (CPU)")
    print("=" * 70)
    print(f"Benchmark Text   : '{sample_text}'")
    print(f"Iterations       : {iterations}")
    print(f"Average Latency  : {avg_latency_us:.2f} microseconds ({avg_latency_ms:.4f} ms)")
    print(f"Throughput       : {iterations / total_time:.0f} calls/second")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_benchmark()

