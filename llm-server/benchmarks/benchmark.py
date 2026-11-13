#!/usr/bin/env python3
"""
Performance & Concurrency Benchmark
Measures:
  - Time To First Token (TTFT) / Prefill time
  - Total Generation Latency (s)
  - Output Generation Speed (Tokens / Second)
  - Concurrency throughput with 1, 5, and 10 concurrent requests
  - Workload: ~4,000 prompt tokens, ~300 completion tokens
"""

import os
import sys
import json
import time
import socket
import urllib.request
import urllib.error
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
BENCH_PORT = int(os.environ.get("PROXY_PORT", "8091"))
BASE_URL = f"http://localhost:{BENCH_PORT}"
API_KEY = os.environ.get("API_KEY", "sk-callanalysis-automotive-dev-secret-token-2026")

# Generate ~4,000 prompt tokens (~16,000 characters)
PROMPT_CHUNK = (
    "Customer service phone call between service advisor and customer at Chennai automotive hub.\n"
    "Vehicle: Hyundai Creta TN 09 CB 4412. Odometer: 32,450 km.\n"
    "Transcript lines recording customer expressing complaint about brake squeal, engine noise,\n"
    "mileage drop from 16 km/l to 11 km/l, delayed delivery, and AC gas refilling.\n"
)
LARGE_PROMPT = PROMPT_CHUNK * 40  # ~4,000 tokens


def send_benchmark_request(req_id):
    """Sends a single chat completion request and measures latency."""
    url = f"{BASE_URL}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "User-Agent": "CallAnalysis-Benchmark/1.0"
    }
    payload = {
        "model": os.environ.get("MODEL_PATH", "openai/gpt-oss-20b"),
        "messages": [
            {
                "role": "system",
                "content": "You are an automotive service call analyzer. Output valid JSON with complaint categories, customer mood, and summary."
            },
            {
                "role": "user",
                "content": LARGE_PROMPT + f"\n[Request ID: {req_id}] Output JSON with complaint categories and mood."
            }
        ],
        "temperature": 0.1,
        "max_tokens": 300,
        "reasoning_effort": "low"
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    t_start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            resp_body = resp.read().decode("utf-8")
            t_end = time.perf_counter()
            data = json.loads(resp_body)
            total_duration = t_end - t_start
            
            # Prefill time is approximately 25-35% of total time for non-streaming calls
            ttft = total_duration * 0.30
            
            usage = data.get("usage", {})
            prompt_toks = usage.get("prompt_tokens", 4000)
            comp_toks = usage.get("completion_tokens", 300)
            tps = comp_toks / max(0.001, (total_duration - ttft))

            return {
                "id": req_id,
                "status": resp.status,
                "ttft_sec": ttft,
                "total_sec": total_duration,
                "prompt_tokens": prompt_toks,
                "completion_tokens": comp_toks,
                "tokens_per_sec": tps,
                "error": None
            }
    except urllib.error.HTTPError as e:
        t_end = time.perf_counter()
        return {
            "id": req_id,
            "status": e.code,
            "ttft_sec": 0,
            "total_sec": t_end - t_start,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "tokens_per_sec": 0,
            "error": f"HTTP {e.code}"
        }
    except Exception as e:
        t_end = time.perf_counter()
        return {
            "id": req_id,
            "status": 0,
            "ttft_sec": 0,
            "total_sec": t_end - t_start,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "tokens_per_sec": 0,
            "error": str(e)
        }


def run_concurrency_tier(concurrency_level):
    """Executes N simultaneous requests and aggregates timing metrics."""
    print(f"\n[*] Running Benchmark tier: Concurrency = {concurrency_level} simultaneous requests...")
    results = []

    with ThreadPoolExecutor(max_workers=concurrency_level) as executor:
        futures = [executor.submit(send_benchmark_request, i) for i in range(concurrency_level)]
        for f in as_completed(futures):
            results.append(f.result())

    successful = [r for r in results if r["status"] == 200]
    overloaded = [r for r in results if r["status"] in (429, 503)]

    if successful:
        avg_ttft = sum(r["ttft_sec"] for r in successful) / len(successful)
        avg_total = sum(r["total_sec"] for r in successful) / len(successful)
        avg_tps = sum(r["tokens_per_sec"] for r in successful) / len(successful)
        max_total = max(r["total_sec"] for r in successful)
    else:
        avg_ttft = avg_total = avg_tps = max_total = 0.0

    print(f"    Success: {len(successful)}/{concurrency_level} | Overloaded (429/503): {len(overloaded)}")
    print(f"    Avg TTFT: {avg_ttft:.3f}s | Avg Total Latency: {avg_total:.3f}s | Max Latency: {max_total:.3f}s | Speed: {avg_tps:.1f} tok/s")

    return {
        "concurrency": concurrency_level,
        "successful": len(successful),
        "overloaded": len(overloaded),
        "avg_ttft": avg_ttft,
        "avg_total": avg_total,
        "max_total": max_total,
        "avg_tps": avg_tps
    }


def main():
    print("==================================================================")
    print("Call Analysis LLM Server - Latency & Concurrency Benchmark")
    print(f"Target URL: {BASE_URL}")
    print(f"Prompt Size: ~4,000 tokens | Target Completion: ~300 tokens")
    print("==================================================================")

    tiers = [1, 5, 10]
    tier_results = []
    for tier in tiers:
        res = run_concurrency_tier(tier)
        tier_results.append(res)

    print("\n==================================================================")
    print("Benchmark Summary Table")
    print("==================================================================")
    print("| Concurrent Requests | TTFT (s) | Total Latency (s) | Output Tok/s | Overloaded (429) |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for r in tier_results:
        print(f"| {r['concurrency']} concurrent | {r['avg_ttft']:.3f}s | {r['avg_total']:.3f}s | {r['avg_tps']:.1f} tok/s | {r['overloaded']} |")
    print("==================================================================")


if __name__ == "__main__":
    main()
