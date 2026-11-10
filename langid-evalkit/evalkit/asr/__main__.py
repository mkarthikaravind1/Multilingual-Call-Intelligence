"""CLI for Speech-to-Text evaluation: python -m evalkit.asr --server <url> --data <folder>"""

import argparse
import json
import os
import sys
import time
from typing import List

from evalkit.asr.adapters import HTTPASRAdapter, MockASRAdapter, BaseASRAdapter
from evalkit.asr.metrics import (
    ClipASRMetric,
    LanguageASRSummary,
    aggregate_asr_metrics,
    compute_cer,
    compute_wer,
)
from evalkit.asr.normalize import normalize_text


def parse_args():
    parser = argparse.ArgumentParser(
        description="Speech-to-Text Evaluation Kit (evalkit.asr)"
    )
    parser.add_argument(
        "--server",
        type=str,
        default=None,
        help="Base URL for ASR server (e.g. http://localhost:8000)",
    )
    parser.add_argument(
        "--data",
        type=str,
        required=True,
        help="Path to folder containing audio clips and manifest.jsonl",
    )
    parser.add_argument(
        "--adapter",
        type=str,
        choices=["http", "mock"],
        default="http",
        help="Adapter to use ('http' or 'mock')",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to save JSON results",
    )
    return parser.parse_args()


def run_asr_eval(adapter: BaseASRAdapter, data_folder: str) -> List[ClipASRMetric]:
    manifest_path = os.path.join(data_folder, "manifest.jsonl")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Missing manifest.jsonl in data folder: {manifest_path}")

    clip_metrics: List[ClipASRMetric] = []

    with open(manifest_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            audio_rel = item["audio"]
            audio_path = os.path.join(data_folder, audio_rel) if not os.path.isabs(audio_rel) else audio_rel
            lang = item.get("language", "unknown")
            ref_raw = item["reference"]

            t0 = time.perf_counter()
            resp = adapter.transcribe(audio_path, language=lang if lang != "unknown" else None)
            t1 = time.perf_counter()
            latency = t1 - t0

            # Calculate audio duration if reported, otherwise fallback
            audio_duration = resp.duration if resp.duration > 0 else max(latency, 0.1)

            ref_norm = normalize_text(ref_raw)
            hyp_norm = normalize_text(resp.transcript)

            wer = compute_wer(ref_norm, hyp_norm)
            cer = compute_cer(ref_norm, hyp_norm)
            words_right = max(0.0, 1.0 - wer)
            rtf = latency / audio_duration

            clip_metrics.append(
                ClipASRMetric(
                    audio_file=audio_rel,
                    language=lang,
                    reference_raw=ref_raw,
                    reference_norm=ref_norm,
                    hypothesis_raw=resp.transcript,
                    hypothesis_norm=hyp_norm,
                    wer=wer,
                    cer=cer,
                    words_right=words_right,
                    latency_sec=latency,
                    audio_duration_sec=audio_duration,
                    rtf=rtf,
                )
            )

    return clip_metrics


def print_asr_table(summaries: dict):
    header = (
        f"{'Language':<12} | {'Clips':<6} | {'Words Right':<12} | "
        f"{'WER':<8} | {'CER':<8} | {'Avg Latency':<12} | {'RTF':<8}"
    )
    sep = "-" * len(header)
    print("\n" + sep)
    print(" SPEECH-TO-TEXT EVALUATION RESULTS")
    print(sep)
    print(header)
    print(sep)

    # Order: specific languages first, then OVERALL
    langs = [k for k in summaries if k != "OVERALL"] + (["OVERALL"] if "OVERALL" in summaries else [])
    for lang in langs:
        s: LanguageASRSummary = summaries[lang]
        wr_str = f"{s.words_right * 100:.2f}%"
        wer_str = f"{s.wer * 100:.2f}%"
        cer_str = f"{s.cer * 100:.2f}%"
        lat_str = f"{s.avg_latency_sec:.2f} s"
        rtf_str = f"{s.rtf:.2f}x"
        print(f"{s.language:<12} | {s.total_clips:<6} | {wr_str:<12} | {wer_str:<8} | {cer_str:<8} | {lat_str:<12} | {rtf_str:<8}")
    print(sep + "\n")


def main():
    args = parse_args()
    if args.adapter == "http":
        if not args.server:
            print("Error: --server is required when using HTTP adapter.", file=sys.stderr)
            sys.exit(1)
        adapter = HTTPASRAdapter(base_url=args.server)
    else:
        adapter = MockASRAdapter()

    metrics = run_asr_eval(adapter, args.data)
    summaries = aggregate_asr_metrics(metrics)
    print_asr_table(summaries)

    if args.output:
        out_dict = {
            "summaries": {
                k: {
                    "language": v.language,
                    "total_clips": v.total_clips,
                    "words_right": v.words_right,
                    "wer": v.wer,
                    "cer": v.cer,
                    "avg_latency_sec": v.avg_latency_sec,
                    "rtf": v.rtf,
                }
                for k, v in summaries.items()
            },
            "clips": [m.__dict__ for m in metrics],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out_dict, f, indent=2, ensure_ascii=False)
        print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()

