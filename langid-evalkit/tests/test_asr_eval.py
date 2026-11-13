"""Unit tests for evalkit.asr: Speech-to-text evaluation."""

import json
import os
import tempfile
import httpx
import pytest

from evalkit.asr.adapters import HTTPASRAdapter, MockASRAdapter
from evalkit.asr.dataset_builder import build_sample_dataset, emulate_phone_audio, generate_synthetic_phone_clip
from evalkit.asr.metrics import (
    aggregate_asr_metrics,
    compute_cer,
    compute_wer,
    edit_distance,
)
from evalkit.asr.normalize import normalize_text
from evalkit.asr.__main__ import run_asr_eval


def test_normalization():
    # Punctuation and case folding
    raw = "Hello, Sir! Your car is ready... Right?"
    assert normalize_text(raw) == "hello sir your car is ready right"

    # Indic dandas and zero-width non-joiner
    indic_raw = "வணக்கம்\u200C சார்! உங்கள் வண்டி ரெடி। ॥"
    assert normalize_text(indic_raw) == "வணக்கம் சார் உங்கள் வண்டி ரெடி"

    # Multiple whitespace
    assert normalize_text("  a \t b   \n c  ") == "a b c"


def test_edit_distance_and_error_rates():
    assert edit_distance(["hello", "world"], ["hello", "world"]) == 0
    assert edit_distance(["hello", "world"], ["hello", "there", "world"]) == 1

    # WER
    ref = "vanakkam sir car ready"
    hyp_exact = "vanakkam sir car ready"
    assert compute_wer(ref, hyp_exact) == 0.0

    hyp_sub = "vanakkam sir bike ready"
    assert compute_wer(ref, hyp_sub) == 0.25

    # CER
    ref_ta = "வணக்கம்"
    hyp_ta = "வணகம்"
    assert compute_cer(ref_ta, hyp_ta) > 0.0


def test_http_adapter_with_mock_transport(tmp_path):
    audio_file = tmp_path / "dummy.wav"
    audio_file.write_bytes(b"RIFFdummydataWAVEfmt ")

    def mock_handler(request: httpx.Request):
        assert "/v1/transcribe" in request.url.path
        return httpx.Response(
            200,
            json={
                "transcript": "வணக்கம் சார்",
                "language": "ta",
                "confidence": 0.95,
                "duration": 2.0,
                "no_speech": False,
                "segments": [{"text": "வணக்கம் சார்", "start": 0.0, "end": 2.0}],
            },
        )

    adapter = HTTPASRAdapter(base_url="http://fake-asr-server.local")
    # Patch transport
    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "Client", lambda *args, **kwargs: mock_client)
        resp = adapter.transcribe(str(audio_file), language="ta")
        assert resp.transcript == "வணக்கம் சார்"
        assert resp.language == "ta"
        assert resp.duration == 2.0


def test_run_asr_eval_with_mock_adapter(tmp_path):
    dataset_dir = tmp_path / "asr_data"
    build_sample_dataset(str(dataset_dir))

    adapter = MockASRAdapter(
        canned_responses={
            "call_ta_01.wav": "வணக்கம் சார் உங்கள் வண்டி சர்வீஸ் முடிந்தது பிரேக் மாற்றப்பட்டது"
        },
        simulated_latency=0.001,
    )

    metrics = run_asr_eval(adapter, str(dataset_dir))
    assert len(metrics) == 5

    # Check that Tamil clip got 100% words right
    ta_clip = next(m for m in metrics if m.language == "ta")
    assert ta_clip.wer == 0.0
    assert ta_clip.words_right == 1.0

    summaries = aggregate_asr_metrics(metrics)
    assert "ta" in summaries
    assert "OVERALL" in summaries
    assert summaries["ta"].words_right == 1.0


def test_phone_audio_resampling(tmp_path):
    orig_wav = tmp_path / "test_orig.wav"
    phone_wav = tmp_path / "test_phone.wav"
    generate_synthetic_phone_clip(str(orig_wav), duration_sec=0.5, freq=400.0)
    assert os.path.exists(orig_wav)

    emulate_phone_audio(str(orig_wav), str(phone_wav))
    assert os.path.exists(phone_wav)
    assert os.path.getsize(phone_wav) > 1000

