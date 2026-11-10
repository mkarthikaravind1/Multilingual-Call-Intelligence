"""CLI for concurrent load testing: python -m evalkit.load --speech <url> --llm <url> --calls 10"""

import argparse
import asyncio
import json
import os
import sys

from evalkit.load.runner import run_load_test


def parse_args():
    parser = argparse.ArgumentParser(description="Concurrent Call Analysis Load Test (evalkit.load)")
    parser.add_argument("--speech", type=str, required=True, help="Speech WebSocket URL (e.g. ws://localhost:8000)")
    parser.add_argument("--llm", type=str, required=True, help="LLM base URL (e.g. http://localhost:8001/v1)")
    parser.add_argument("--calls", type=int, default=10, help="Number of concurrent simulated calls")
    parser.add_argument("--duration", type=float, default=10.0, help="Duration of each simulated call in seconds")
    parser.add_argument("--llm-interval", type=float, default=3.0, help="Interval between LLM queries during a call")
    parser.add_argument("--api-key-env", type=str, default="OPENAI_API_KEY", help="Env var holding API key for LLM")
    parser.add_argument("--output", type=str, default=None, help="Path to write JSON load test metrics")
    return parser.parse_args()


def print_load_summary(metrics: dict):
    sep = "=" * 65
    print("\n" + sep)
    print(" CONCURRENT LOAD TEST REPORT")
    print(sep)
    print(f"Simulated Concurrent Calls       : {metrics['num_calls']}")
    print(f"Total Test Elapsed Time          : {metrics['test_duration_sec']:.2f} s")
    print("-" * 65)
    print("TRANSCRIPT STREAMING LATENCY (SLAs target: <= 2.0 s)")
    tr = metrics["transcripts"]
    print(f"  Total Lines Received           : {tr['total_lines_received']}")
    print(f"  50th Percentile (Median) Delay : {tr['p50_latency_sec']:.3f} s")
    print(f"  95th Percentile (p95) Delay    : {tr['p95_latency_sec']:.3f} s")
    print("-" * 65)
    print("LLM INFERENCE LATENCY (SLAs target: <= 3.0 s)")
    llm = metrics["llm"]
    print(f"  Total Answers Received         : {llm['total_answers_received']}")
    print(f"  50th Percentile (Median) Delay : {llm['p50_latency_sec']:.3f} s")
    print(f"  95th Percentile (p95) Delay    : {llm['p95_latency_sec']:.3f} s")
    print(sep + "\n")


def main():
    args = parse_args()
    api_key = os.environ.get(args.api_key_env, "").strip()

    metrics = asyncio.run(
        run_load_test(
            speech_url=args.speech,
            llm_url=args.llm,
            num_calls=args.calls,
            call_duration_sec=args.duration,
            llm_interval_sec=args.llm_interval,
            api_key=api_key or None,
        )
    )

    print_load_summary(metrics)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        print(f"Load test metrics saved to {args.output}")


if __name__ == "__main__":
    main()

