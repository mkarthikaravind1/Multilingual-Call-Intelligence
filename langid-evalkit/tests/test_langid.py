"""Unit tests for langid: Native and Romanised Indian language identification."""

import time
import pytest
from langid import identify


def test_empty_and_unclear_text():
    assert identify("") == []
    assert identify("   ") == []
    assert identify("1234567890") == []
    assert identify("!@#$%^&*()_+{}[]") == []


def test_native_scripts():
    # Tamil
    res_ta = identify("வணக்கம் சார் உங்கள் வண்டி சர்வீஸ் முடிந்தது")
    assert len(res_ta) >= 1
    assert res_ta[0]["language"] == "ta"
    assert res_ta[0]["confidence"] > 0.8

    # Telugu
    res_te = identify("నమస్కారం సార్ మీ కారు సర్వీస్ పూర్తయింది")
    assert len(res_te) >= 1
    assert res_te[0]["language"] == "te"
    assert res_te[0]["confidence"] > 0.8

    # Kannada
    res_kn = identify("ನಮಸ್ಕಾರ ಸರ್ ನಿಮ್ಮ ವಾಹನದ ಸರ್ವೀಸ್ ಮುಗಿದಿದೆ")
    assert len(res_kn) >= 1
    assert res_kn[0]["language"] == "kn"
    assert res_kn[0]["confidence"] > 0.8

    # Malayalam
    res_ml = identify("നമസ്കാരം സാർ കാറിന്റെ സർവീസ് കഴിഞ്ഞു")
    assert len(res_ml) >= 1
    assert res_ml[0]["language"] == "ml"
    assert res_ml[0]["confidence"] > 0.8


def test_pure_english():
    res_en = identify("Good morning sir your vehicle brake pads have been replaced today")
    assert len(res_en) == 1
    assert res_en[0]["language"] == "en"
    assert res_en[0]["confidence"] == 1.0


def test_romanised_tamil_tanglish_code_mixed():
    # Prompt example: "enna problem sir, brake sariya work aagala" -> ta and en
    res = identify("enna problem sir, brake sariya work aagala")
    langs = [r["language"] for r in res]
    assert "ta" in langs
    assert "en" in langs
    # Top confidence first
    assert res[0]["confidence"] >= res[1]["confidence"]


def test_romanised_telugu_tenglish():
    res = identify("enti problem babu, engine sound vastundi cheppandi")
    langs = [r["language"] for r in res]
    assert "te" in langs
    assert "en" in langs


def test_romanised_kannada_kanglish():
    res = identify("enu problem agide sir, service madabeku")
    langs = [r["language"] for r in res]
    assert "kn" in langs
    assert "en" in langs


def test_romanised_malayalam_manglish():
    res = identify("entha problem aanu sir, brake work aavunnilla")
    langs = [r["language"] for r in res]
    assert "ml" in langs
    assert "en" in langs


def test_speed_latency_under_5ms():
    text = "enna problem sir, brake sariya work aagala"
    # Warmup
    identify(text)

    t0 = time.perf_counter()
    iterations = 500
    for _ in range(iterations):
        identify(text)
    avg_ms = ((time.perf_counter() - t0) / iterations) * 1000.0
    print(f"\nAverage identify() execution time: {avg_ms:.3f} ms")
    assert avg_ms < 5.0, f"Expected < 5ms, got {avg_ms} ms"

